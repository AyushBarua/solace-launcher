"""
tests/test_updater.py
Unit tests for the update checker: version comparison, release parsing, the
download allow-list, checksum verification and the settings switch.
Run with: pytest tests/
"""
import hashlib
import io
import os
import urllib.error

import pytest

from core import updater


# ── Helpers ───────────────────────────────────────────────────────────────────

def _release(tag="v1.2.0", **overrides):
    base = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/AyushBarua/solace-launcher/releases/tag/" + tag,
        "body": "Notes for " + tag,
        "assets": [
            {"name": "Solace_Setup.exe",
             "browser_download_url": "https://github.com/AyushBarua/solace-launcher/releases/download/%s/Solace_Setup.exe" % tag,
             "size": 1234},
            {"name": "Solace_Setup.exe.sha256",
             "browser_download_url": "https://github.com/AyushBarua/solace-launcher/releases/download/%s/Solace_Setup.exe.sha256" % tag,
             "size": 100},
        ],
    }
    base.update(overrides)
    return base


class _FakeResponse(io.BytesIO):
    """Minimal stand-in for what urlopen returns."""

    def __init__(self, data: bytes, url: str = "https://github.com/x", length=True):
        super().__init__(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))} if length else {}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ── Version comparison ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("1.2.3", (1, 2, 3)),
    ("v1.2.3", (1, 2, 3)),
    ("V2.0", (2, 0)),
    ("1.0.0-dev", (1, 0, 0)),
    ("  v10.20.30  ", (10, 20, 30)),
])
def test_parse_version_accepts_normal_forms(text, expected):
    assert updater.parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "latest", "v", "1.x.2", None, "1..2"])
def test_parse_version_rejects_junk(text):
    assert updater.parse_version(text) is None


def test_is_newer_compares_numerically_not_as_text():
    assert updater.is_newer("1.10.0", "1.9.0")
    assert not updater.is_newer("1.9.0", "1.10.0")


def test_is_newer_false_when_equal_or_older():
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert not updater.is_newer("v1.0.0", "1.0.0")
    assert not updater.is_newer("0.9.9", "1.0.0")


def test_is_newer_treats_missing_parts_as_zero():
    assert not updater.is_newer("1.0", "1.0.0")
    assert updater.is_newer("1.0.1", "1.0")


def test_is_newer_false_when_either_side_is_unreadable():
    assert not updater.is_newer("nightly", "1.0.0")
    assert not updater.is_newer("1.0.0", "garbage")


# ── Release parsing ───────────────────────────────────────────────────────────

def test_parse_release_reads_version_assets_and_notes():
    info = updater.parse_release(_release("v1.2.0"))
    assert info.version == "1.2.0"
    assert info.installer_url.endswith("/v1.2.0/Solace_Setup.exe")
    assert info.checksum_url.endswith("/v1.2.0/Solace_Setup.exe.sha256")
    assert info.notes == "Notes for v1.2.0"
    assert info.page_url.endswith("/tag/v1.2.0")


def test_parse_release_ignores_drafts_and_prereleases():
    assert updater.parse_release(_release(draft=True)) is None
    assert updater.parse_release(_release(prerelease=True)) is None


def test_parse_release_needs_installer_and_checksum():
    only_installer = _release()
    only_installer["assets"] = only_installer["assets"][:1]
    assert updater.parse_release(only_installer) is None

    no_assets = _release()
    no_assets["assets"] = []
    assert updater.parse_release(no_assets) is None


def test_parse_release_rejects_unreadable_tag():
    assert updater.parse_release(_release("nightly")) is None


def test_parse_release_tolerates_missing_body():
    payload = _release()
    payload["body"] = None
    assert updater.parse_release(payload).notes == ""


def test_parse_release_rejects_download_url_on_other_host():
    payload = _release()
    payload["assets"][0]["browser_download_url"] = "https://evil.example.com/Solace_Setup.exe"
    assert updater.parse_release(payload) is None


def test_parse_release_rejects_plain_http():
    payload = _release()
    payload["assets"][0]["browser_download_url"] = "http://github.com/x/Solace_Setup.exe"
    assert updater.parse_release(payload) is None


# ── Download allow-list ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "https://github.com/AyushBarua/solace-launcher/releases/download/v1/Solace_Setup.exe",
    "https://objects.githubusercontent.com/abc",
    "https://release-assets.githubusercontent.com/abc",
    "https://api.github.com/repos/AyushBarua/solace-launcher/releases/latest",
])
def test_allowed_urls(url):
    assert updater.is_allowed_url(url)


@pytest.mark.parametrize("url", [
    "http://github.com/x",
    "https://github.com.evil.com/x",
    "https://evilgithub.com/x",
    "https://example.com/x",
    "ftp://github.com/x",
    "file:///C:/Windows/System32/cmd.exe",
    "",
])
def test_blocked_urls(url):
    assert not updater.is_allowed_url(url)


# ── Checking for an update ────────────────────────────────────────────────────

def test_check_for_update_returns_info_when_newer():
    info = updater.check_for_update("1.0.0", fetch=lambda: _release("v1.1.0"))
    assert info is not None and info.version == "1.1.0"


def test_check_for_update_returns_none_when_current():
    assert updater.check_for_update("1.1.0", fetch=lambda: _release("v1.1.0")) is None


def test_check_for_update_returns_none_when_release_unusable():
    assert updater.check_for_update("1.0.0", fetch=lambda: _release(draft=True)) is None


def test_check_for_update_wraps_network_errors():
    def boom():
        raise urllib.error.URLError("no network")
    with pytest.raises(updater.UpdateError):
        updater.check_for_update("1.0.0", fetch=boom)


def test_fetch_latest_payload_uses_the_api_and_parses_json():
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _FakeResponse(b'{"tag_name": "v9.9.9"}', url=request.full_url)

    payload = updater.fetch_latest_payload(opener=opener, timeout=5)
    assert payload == {"tag_name": "v9.9.9"}
    assert seen["url"] == updater.LATEST_RELEASE_API
    assert seen["timeout"] == 5


def test_fetch_latest_payload_rejects_bad_json():
    def opener(request, timeout=None):
        return _FakeResponse(b"<html>rate limited</html>", url=request.full_url)

    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_payload(opener=opener)


# ── Checksums and downloading ─────────────────────────────────────────────────

def test_parse_checksum_reads_hash_from_common_formats():
    digest = hashlib.sha256(b"x").hexdigest()
    assert updater.parse_checksum(digest) == digest
    assert updater.parse_checksum(digest + "  Solace_Setup.exe\n") == digest
    assert updater.parse_checksum(digest.upper() + " *Solace_Setup.exe") == digest


@pytest.mark.parametrize("text", ["", "not a hash", "abc123", "z" * 64])
def test_parse_checksum_rejects_garbage(text):
    assert updater.parse_checksum(text) is None


def _opener_for(installer: bytes, checksum_text: str):
    def opener(request, timeout=None):
        url = request.full_url
        if url.endswith(".sha256"):
            return _FakeResponse(checksum_text.encode(), url=url)
        return _FakeResponse(installer, url=url)
    return opener


def test_download_installer_saves_a_verified_file(tmp_path):
    data = b"MZ" + b"\x00" * 5000
    digest = hashlib.sha256(data).hexdigest()
    info = updater.parse_release(_release("v1.2.0"))
    progress = []

    path = updater.download_installer(
        info, str(tmp_path), progress=lambda done, total: progress.append((done, total)),
        opener=_opener_for(data, digest + "  Solace_Setup.exe"))

    assert os.path.basename(path) == "Solace_Setup.exe"
    assert open(path, "rb").read() == data
    assert progress and progress[-1][0] == len(data)
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".part")]


def test_download_installer_deletes_file_on_checksum_mismatch(tmp_path):
    data = b"MZ" + b"\x01" * 4000
    wrong = hashlib.sha256(b"something else").hexdigest()
    info = updater.parse_release(_release("v1.2.0"))

    with pytest.raises(updater.UpdateError):
        updater.download_installer(info, str(tmp_path), opener=_opener_for(data, wrong))

    assert os.listdir(tmp_path) == []


def test_download_installer_refuses_missing_checksum(tmp_path):
    info = updater.parse_release(_release("v1.2.0"))
    with pytest.raises(updater.UpdateError):
        updater.download_installer(info, str(tmp_path), opener=_opener_for(b"MZ", "no hash here"))
    assert os.listdir(tmp_path) == []


def test_download_installer_refuses_redirect_to_other_host(tmp_path):
    data = b"MZ" + b"\x02" * 100
    digest = hashlib.sha256(data).hexdigest()
    info = updater.parse_release(_release("v1.2.0"))

    def opener(request, timeout=None):
        if request.full_url.endswith(".sha256"):
            return _FakeResponse(digest.encode(), url=request.full_url)
        return _FakeResponse(data, url="https://evil.example.com/Solace_Setup.exe")

    with pytest.raises(updater.UpdateError):
        updater.download_installer(info, str(tmp_path), opener=opener)
    assert os.listdir(tmp_path) == []


def test_download_installer_replaces_an_older_download(tmp_path):
    old = tmp_path / "Solace_Setup.exe"
    old.write_bytes(b"old build")
    data = b"MZ" + b"\x03" * 50
    info = updater.parse_release(_release("v1.2.0"))

    path = updater.download_installer(
        info, str(tmp_path), opener=_opener_for(data, hashlib.sha256(data).hexdigest()))
    assert open(path, "rb").read() == data


# ── Settings switch ───────────────────────────────────────────────────────────

def test_check_is_on_by_default():
    assert updater.is_check_enabled({}) is True


def test_check_can_be_switched_off_and_on():
    assert updater.is_check_enabled({"check_updates": False}) is False
    assert updater.is_check_enabled({"check_updates": True}) is True


def test_check_ignores_non_boolean_values():
    assert updater.is_check_enabled({"check_updates": "no"}) is True


def test_should_check_on_start_only_for_installed_builds(monkeypatch):
    monkeypatch.delenv("SOLACE_FORCE_UPDATE_CHECK", raising=False)
    assert updater.should_check_on_start({}, frozen=True) is True
    assert updater.should_check_on_start({}, frozen=False) is False
    assert updater.should_check_on_start({"check_updates": False}, frozen=True) is False


def test_force_variable_enables_the_check_in_development(monkeypatch):
    monkeypatch.setenv("SOLACE_FORCE_UPDATE_CHECK", "1")
    assert updater.should_check_on_start({}, frozen=False) is True
    assert updater.should_check_on_start({"check_updates": False}, frozen=False) is False


# ── Reading and saving the switch ─────────────────────────────────────────────

def test_save_check_enabled_round_trips_and_keeps_other_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLACE_DATA_DIR", str(tmp_path))
    (tmp_path / "global_settings.json").write_text(
        '{"theme": "dark", "ui_scale": 1.25}', encoding="utf-8")

    updater.save_check_enabled(False)
    settings = updater.load_settings()

    assert settings == {"theme": "dark", "ui_scale": 1.25, "check_updates": False}
    assert updater.is_check_enabled(settings) is False


def test_load_settings_survives_a_missing_or_broken_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLACE_DATA_DIR", str(tmp_path))
    assert updater.load_settings() == {}
    (tmp_path / "global_settings.json").write_text("{not json", encoding="utf-8")
    assert updater.load_settings() == {}


def test_save_check_enabled_creates_the_file_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SOLACE_DATA_DIR", str(tmp_path))
    updater.save_check_enabled(True)
    assert updater.load_settings() == {"check_updates": True}


# ── Starting the installer ────────────────────────────────────────────────────

def test_launch_installer_asks_windows_to_run_it_elevated(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    calls = []

    def fake_shell_execute(*args):
        calls.append(args)
        return 42

    updater.launch_installer(r"C:\Temp\Solace_Setup.exe", shell_execute=fake_shell_execute)

    _hwnd, verb, target, params, _cwd, _show = calls[0]
    assert verb == "runas"
    assert target == r"C:\Temp\Solace_Setup.exe"
    assert "/SILENT" in params and "/CLOSEAPPLICATIONS" in params


def test_launch_installer_raises_when_windows_refuses(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    with pytest.raises(OSError):
        updater.launch_installer(r"C:\Temp\Solace_Setup.exe", shell_execute=lambda *a: 5)


def test_launch_installer_raises_when_windows_returns_nothing(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    with pytest.raises(OSError):
        updater.launch_installer(r"C:\Temp\Solace_Setup.exe", shell_execute=lambda *a: None)
