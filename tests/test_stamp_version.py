"""
tests/test_stamp_version.py
The release workflow stamps the tag into core/version.py before building.
Run with: pytest tests/
"""
import importlib.util
import os

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "stamp_version.py")


def _load():
    spec = importlib.util.spec_from_file_location("stamp_version", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _version_file(tmp_path, line='__version__ = "0.0.0-dev"'):
    path = tmp_path / "version.py"
    path.write_text('"""Docstring."""\n\n' + line + "\n", encoding="utf-8")
    return str(path)


def test_stamp_replaces_only_the_version_line(tmp_path):
    path = _version_file(tmp_path)
    _load().stamp(path, "1.4.2")
    text = open(path, encoding="utf-8").read()
    assert '__version__ = "1.4.2"' in text
    assert "0.0.0-dev" not in text
    assert text.startswith('"""Docstring."""')


def test_stamp_accepts_a_leading_v(tmp_path):
    path = _version_file(tmp_path)
    _load().stamp(path, "v2.0.0")
    assert '__version__ = "2.0.0"' in open(path, encoding="utf-8").read()


@pytest.mark.parametrize("bad", ["", "latest", "1.x", 'x"; import os; "'])
def test_stamp_rejects_unreadable_versions(tmp_path, bad):
    path = _version_file(tmp_path)
    with pytest.raises(ValueError):
        _load().stamp(path, bad)
    assert '0.0.0-dev' in open(path, encoding="utf-8").read()


def test_stamp_fails_if_the_version_line_is_missing(tmp_path):
    path = _version_file(tmp_path, line="VERSION = 1")
    with pytest.raises(ValueError):
        _load().stamp(path, "1.0.0")
