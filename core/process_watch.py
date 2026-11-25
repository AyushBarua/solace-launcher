"""
core/process_watch.py

A game started through Steam or Epic is not a child of Solace, so there is no
process to wait on. Instead this watches for any running program whose file is
inside the game's install folder, and reports when the last one has closed.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Callable

START_TIMEOUT = 180.0        # stores can take a while to update and launch
POLL_SECONDS = 2.0
GONE_CHECKS = 3              # misses in a row before the game counts as closed


def _norm(path: str) -> str:
    return os.path.normpath(path.replace("/", os.sep)).lower()


def any_under(paths: list, folder: str) -> bool:
    if not folder:
        return False
    prefix = _norm(folder).rstrip(os.sep) + os.sep
    return any(_norm(p).startswith(prefix) for p in paths)


def list_process_paths() -> list:
    """Program file paths of the running processes this user may inspect."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    ids = (wintypes.DWORD * 8192)()
    used = wintypes.DWORD()
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(used)):
        return []
    paths = []
    for pid in ids[: used.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel32.OpenProcess(0x1000, False, pid)    # QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            paths.append(buffer.value)
        kernel32.CloseHandle(handle)
    return paths


def wait_for_game(install_dir: str, list_paths: Callable[[], list] = list_process_paths,
                  sleep: Callable[[float], None] = time.sleep,
                  start_timeout: float = START_TIMEOUT, poll: float = POLL_SECONDS) -> bool:
    """Block until the game has started and closed again.

    Returns False if nothing from the folder started within start_timeout."""
    waited = 0.0
    while not any_under(list_paths(), install_dir):
        if waited >= start_timeout:
            return False
        sleep(poll)
        waited += poll
    misses = 0
    while misses < GONE_CHECKS:      # a launcher stub may exit before the game appears
        sleep(poll)
        misses = 0 if any_under(list_paths(), install_dir) else misses + 1
    return True
