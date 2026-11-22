"""
cloud_sync — SIMULATED cloud backup (§6.3).

There is no backend yet. This stub records that a profile's data *would* sync to
its owning account, and exposes a friendly status the UI can show. The important
part — WHICH account owns the data — is real, so swapping this for real API calls
later (Tier 5) needs no data-model changes.

State is kept per data-dir in cloud_sync.json:
    { "<account_id>": {"last_synced": iso, "pending": bool} }
"""
import os
import json
import threading
from datetime import datetime
from typing import Optional


def _path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "cloud_sync.json")


def _load() -> dict:
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    try:
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, _path())
    except Exception:
        pass


def mark_pending(account_id: Optional[str]):
    """Call after a session is recorded — data is 'waiting to sync'."""
    if not account_id:
        return
    d = _load()
    d.setdefault(account_id, {})["pending"] = True
    _save(d)
    # Simulate a network round-trip that completes shortly after.
    threading.Timer(2.5, lambda: _complete(account_id)).start()


def _complete(account_id: str):
    d = _load()
    entry = d.setdefault(account_id, {})
    entry["pending"] = False
    entry["last_synced"] = datetime.now().isoformat()
    _save(d)


def status(account_id: Optional[str]) -> str:
    """Human-readable sync status for the UI (simulated)."""
    if not account_id:
        return "Not linked to an account"
    entry = _load().get(account_id, {})
    if entry.get("pending"):
        return "Syncing…"
    ts = entry.get("last_synced")
    if ts:
        try:
            when = datetime.fromisoformat(ts).strftime("%b %d, %H:%M")
            return f"Backed up  (last: {when})"
        except Exception:
            return "Backed up"
    return "Backup pending"
