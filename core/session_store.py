"""
SessionStore — persists the logged-in user between app launches.

Saves a session token to %LOCALAPPDATA%\Solace\session.json.
Sessions expire after SESSION_DAYS days; on expiry the user is prompted
to log in again (good for shared clinic devices or security-conscious users).

Usage:
    from core.session_store import save_session, load_session, clear_session

    save_session(user_dict)         # call after successful login
    user = load_session()           # returns user dict or None if expired/missing
    clear_session()                 # call on logout
"""
import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional

SESSION_DAYS = 30   # how long a remembered session lasts


def _get_session_path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "session.json")


def save_session(user: dict):
    """
    Persist user to disk. Call after every successful login.
    user must contain at least: id, name, identifier, provider
    """
    path = _get_session_path()
    data = {
        "token":      str(uuid.uuid4()),   # opaque local token
        "user":       user,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat(),
    }
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass  # non-fatal — user just has to log in again next time


def load_session() -> Optional[dict]:
    """
    Returns the saved user dict if session exists and hasn't expired.
    Returns None if missing, malformed, or expired.
    """
    path = _get_session_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        expires_at = datetime.fromisoformat(data["expires_at"])
        if datetime.now() > expires_at:
            clear_session()
            return None
        return data.get("user")
    except Exception:
        return None


def clear_session():
    """Call on explicit logout or session expiry."""
    path = _get_session_path()
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def is_session_valid() -> bool:
    return load_session() is not None


# ── Remembered email (pre-fill when "keep signed in" is OFF) ──────────────────

def _last_email_path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "last_email.json")


def save_last_email(email: str):
    try:
        with open(_last_email_path(), "w", encoding="utf-8") as f:
            json.dump({"email": (email or "").strip()}, f)
    except Exception:
        pass


def load_last_email() -> str:
    try:
        with open(_last_email_path(), "r", encoding="utf-8") as f:
            return json.load(f).get("email", "")
    except Exception:
        return ""
