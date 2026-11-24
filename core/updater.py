"""
core/updater.py

Looks for a newer Solace on GitHub Releases and downloads its installer.

No Qt in here, so it can be tested on its own. The flow:

    check_for_update(current)  ->  UpdateInfo or None
    download_installer(info, folder)  ->  path of a checksum-verified installer
    launch_installer(path)  ->  starts the installer; the caller then quits

A release must carry two assets: Solace_Setup.exe and Solace_Setup.exe.sha256.
The installer is only ever kept and run if its SHA-256 matches the .sha256 file,
and every URL (including redirects) must be https on github.com or
githubusercontent.com.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

REPO = "AyushBarua/solace-launcher"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER_NAME = "Solace_Setup.exe"
CHECKSUM_NAME = INSTALLER_NAME + ".sha256"

REQUEST_TIMEOUT = 8            # seconds, for the version check
DOWNLOAD_TIMEOUT = 30          # seconds without data, for the installer
CHUNK_BYTES = 64 * 1024
MAX_JSON_BYTES = 2_000_000
MAX_CHECKSUM_BYTES = 4096
USER_AGENT = "Solace-Updater"
SETTINGS_KEY = "check_updates"
FORCE_ENV = "SOLACE_FORCE_UPDATE_CHECK"

_ALLOWED_HOSTS = {"github.com", "api.github.com"}
_ALLOWED_SUFFIX = ".githubusercontent.com"
_VERSION_RE = re.compile(r"^\s*[vV]?(\d+(?:\.\d+)*)(?:[-+].*)?\s*$")
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")

ProgressFn = Callable[[int, int], None]


class UpdateError(Exception):
    """Anything that stops an update: network, a bad release, a failed checksum."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    installer_url: str
    checksum_url: str
    notes: str = ""
    page_url: str = ""
    size: int = 0


# ── Versions ──────────────────────────────────────────────────────────────────

def parse_version(text) -> Optional[tuple]:
    """'v1.2.3' -> (1, 2, 3). Anything unreadable gives None."""
    if not isinstance(text, str):
        return None
    match = _VERSION_RE.match(text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest, current) -> bool:
    """True only when both versions are readable and latest is strictly higher."""
    a, b = parse_version(latest), parse_version(current)
    if a is None or b is None:
        return False
    width = max(len(a), len(b))
    pad = lambda v: v + (0,) * (width - len(v))
    return pad(a) > pad(b)


# ── Where downloads may come from ─────────────────────────────────────────────

def is_allowed_url(url: str) -> bool:
    try:
        parts = urlparse(url or "")
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return host in _ALLOWED_HOSTS or (
        host.endswith(_ALLOWED_SUFFIX) and len(host) > len(_ALLOWED_SUFFIX))


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Refuses to follow a redirect that leaves GitHub."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_allowed_url(newurl):
            raise urllib.error.URLError(f"redirect to a disallowed address: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_opener(request, timeout=None):
    return urllib.request.build_opener(_SafeRedirects).open(request, timeout=timeout)


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})


# ── Reading a release ─────────────────────────────────────────────────────────

def parse_release(payload) -> Optional[UpdateInfo]:
    """Turn GitHub's release JSON into an UpdateInfo, or None if it can't be used."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    parsed = parse_version(payload.get("tag_name"))
    if parsed is None:
        return None
    urls, size = {}, 0
    for asset in payload.get("assets") or []:
        name = asset.get("name")
        if name in (INSTALLER_NAME, CHECKSUM_NAME):
            urls[name] = asset.get("browser_download_url", "")
            if name == INSTALLER_NAME:
                size = int(asset.get("size") or 0)
    installer, checksum = urls.get(INSTALLER_NAME), urls.get(CHECKSUM_NAME)
    if not installer or not checksum:
        return None
    if not (is_allowed_url(installer) and is_allowed_url(checksum)):
        return None
    return UpdateInfo(
        version=".".join(str(n) for n in parsed),
        installer_url=installer,
        checksum_url=checksum,
        notes=payload.get("body") or "",
        page_url=payload.get("html_url") or "",
        size=size,
    )


def fetch_latest_payload(opener=None, timeout: float = REQUEST_TIMEOUT) -> dict:
    """GET the latest release. A repository with no releases yet gives {}."""
    opener = opener or _default_opener
    try:
        with opener(_request(LATEST_RELEASE_API), timeout=timeout) as response:
            if not is_allowed_url(response.geturl()):
                raise UpdateError("the update server redirected somewhere unexpected")
            payload = json.loads(response.read(MAX_JSON_BYTES).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        raise UpdateError(f"GitHub answered {exc.code}") from exc
    except (OSError, ValueError) as exc:
        raise UpdateError(f"could not read the latest release: {exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError("unexpected reply from GitHub")
    return payload


def check_for_update(current: str, fetch: Callable[[], dict] = fetch_latest_payload
                     ) -> Optional[UpdateInfo]:
    """The newer release if there is one, else None. Raises UpdateError on failure."""
    try:
        payload = fetch()
    except UpdateError:
        raise
    except (OSError, ValueError) as exc:
        raise UpdateError(str(exc)) from exc
    info = parse_release(payload)
    if info is not None and is_newer(info.version, current):
        return info
    return None


# ── Downloading ───────────────────────────────────────────────────────────────

def parse_checksum(text: str) -> Optional[str]:
    """First 64-digit hex string in the text, lower-cased."""
    match = _SHA256_RE.search(text or "")
    return match.group(1).lower() if match else None


def _fetch_checksum(url: str, opener, timeout: float) -> str:
    try:
        with opener(_request(url), timeout=timeout) as response:
            if not is_allowed_url(response.geturl()):
                raise UpdateError("the checksum redirected somewhere unexpected")
            text = response.read(MAX_CHECKSUM_BYTES).decode("utf-8", "replace")
    except OSError as exc:
        raise UpdateError(f"could not download the checksum: {exc}") from exc
    digest = parse_checksum(text)
    if digest is None:
        raise UpdateError("the release has no readable checksum")
    return digest


def download_installer(info: UpdateInfo, dest_dir: str, progress: Optional[ProgressFn] = None,
                       opener=None, timeout: float = DOWNLOAD_TIMEOUT) -> str:
    """Download the installer into dest_dir and verify it. Returns its path.

    Nothing is left behind on failure; an earlier download is replaced."""
    opener = opener or _default_opener
    expected = _fetch_checksum(info.checksum_url, opener, timeout)
    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.join(dest_dir, INSTALLER_NAME)
    part = target + ".part"
    sha = hashlib.sha256()
    try:
        with opener(_request(info.installer_url), timeout=timeout) as response:
            if not is_allowed_url(response.geturl()):
                raise UpdateError("the installer redirected somewhere unexpected")
            total = int(response.headers.get("Content-Length") or info.size or 0)
            done = 0
            with open(part, "wb") as out:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    out.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if sha.hexdigest() != expected:
            raise UpdateError("the downloaded installer failed its checksum")
        os.replace(part, target)
    except OSError as exc:
        raise UpdateError(f"download failed: {exc}") from exc
    finally:
        if os.path.exists(part):
            os.remove(part)
    return target


INSTALLER_ARGS = ("/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART")
_SHELL_EXECUTE_OK = 32          # ShellExecute returns a value above 32 on success


def _windows_shell_execute():
    import ctypes
    from ctypes import c_int, c_void_p, c_wchar_p
    fn = ctypes.windll.shell32.ShellExecuteW
    fn.argtypes = [c_void_p, c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p, c_int]
    fn.restype = c_void_p
    return fn


def launch_installer(path: str, shell_execute=None) -> None:
    """Start the installer. The caller should quit Solace right after.

    The installer asks for administrator rights, and Windows will not start such a
    program with a plain subprocess call (error 740), so on Windows it goes through
    ShellExecute with the "runas" verb, which shows the usual permission prompt.
    /SILENT shows only a progress window, /CLOSEAPPLICATIONS lets the installer
    close anything still holding Solace's files, and the installer starts Solace
    again when it finishes (see installer.iss). Raises OSError if it did not start,
    for example when the permission prompt is declined."""
    if sys.platform != "win32":
        subprocess.Popen([path, *INSTALLER_ARGS], close_fds=True)
        return
    shell_execute = shell_execute or _windows_shell_execute()
    result = shell_execute(None, "runas", path, " ".join(INSTALLER_ARGS), None, 1)
    if (result or 0) <= _SHELL_EXECUTE_OK:
        raise OSError(f"Windows did not start the installer (code {result or 0})")


# ── Settings ──────────────────────────────────────────────────────────────────

def _settings_path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "global_settings.json")


def load_settings() -> dict:
    """global_settings.json as a dict; {} if it is missing or unreadable."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_check_enabled(on: bool) -> None:
    """Store the switch without touching any other setting."""
    settings = {**load_settings(), SETTINGS_KEY: bool(on)}
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def is_check_enabled(settings: dict) -> bool:
    """The 'check for updates at start-up' switch. On unless explicitly False."""
    value = (settings or {}).get(SETTINGS_KEY, True)
    return value if isinstance(value, bool) else True


def should_check_on_start(settings: dict, frozen: Optional[bool] = None) -> bool:
    """Check only in installed builds (or when forced for testing), and only if on."""
    if not is_check_enabled(settings):
        return False
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    forced = os.environ.get(FORCE_ENV, "").strip() not in ("", "0")
    return frozen or forced
