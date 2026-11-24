"""
Write a release version into core/version.py.

Used by the release workflow before it builds the installer:

    python scripts/stamp_version.py v1.4.2
"""
import os
import re
import sys

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "version.py")
_VERSION = re.compile(r"^[vV]?(\d+(?:\.\d+){1,3})$")
_LINE = re.compile(r'^__version__ = ".*"$', re.MULTILINE)


def stamp(path: str, version: str) -> str:
    """Set __version__ in the file at path and return the version written."""
    match = _VERSION.match(version.strip())
    if not match:
        raise ValueError(f"not a version number: {version!r}")
    clean = match.group(1)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not _LINE.search(text):
        raise ValueError(f"no __version__ line in {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_LINE.sub(f'__version__ = "{clean}"', text, count=1))
    return clean


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: stamp_version.py <version>")
    print(stamp(DEFAULT_PATH, sys.argv[1]))
