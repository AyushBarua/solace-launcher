"""
ProfileManager — stores and loads user profiles.
Each profile has: id, name, avatar (emoji), color, created_at, last_used.
Profiles are saved in profiles.json next to Solace.exe.
"""
import os
import sys
import json
import uuid
from datetime import datetime


def _get_profiles_path():
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "profiles.json")


def load_profiles() -> list[dict]:
    path = _get_profiles_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_profiles(profiles: list[dict]):
    path = _get_profiles_path()
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # atomic on Windows and POSIX


def create_profile(name: str, avatar: str, color: str) -> dict:
    profile = {
        "id": str(uuid.uuid4()),
        "name": name,
        "avatar": avatar,
        "color": color,
        "created_at": datetime.now().isoformat(),
        "last_used": datetime.now().isoformat(),
    }
    profiles = load_profiles()
    profiles.append(profile)
    save_profiles(profiles)
    return profile


def delete_profile(profile_id: str):
    profiles = [p for p in load_profiles() if p["id"] != profile_id]
    save_profiles(profiles)


def delete_profile_completely(profile_id: str) -> dict | None:
    """
    Full account deletion: profile entry + session log (and backup) +
    per-profile input config. Returns the removed profile dict (so the
    caller can also delete the linked login account), or None.
    """
    from core.paths import get_data_dir
    profile = next((p for p in load_profiles() if p["id"] == profile_id), None)
    delete_profile(profile_id)

    data_dir = get_data_dir()
    safe = "".join(c for c in profile_id if c.isalnum() or c in "-_")
    for fname in (f"session_log_{profile_id}.json",
                  f"session_log_{profile_id}.json.bak",
                  f"input_config_{safe}.json"):
        path = os.path.join(data_dir, fname)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            print(f"[ProfileManager] could not delete {fname}: {exc}")
    print(f"[ProfileManager] Profile {profile_id} deleted completely")
    return profile


def set_profile_pin(profile_id: str, pin: str | None):
    """Optional 4-digit privacy PIN on a profile (§6). None/'' clears it."""
    profiles = load_profiles()
    for p in profiles:
        if p["id"] == profile_id:
            if pin:
                p["pin"] = pin
            else:
                p.pop("pin", None)
            break
    save_profiles(profiles)


def get_profile_pin(profile_id: str) -> str | None:
    for p in load_profiles():
        if p["id"] == profile_id:
            return p.get("pin")
    return None


def set_last_used(profile_id: str):
    profiles = load_profiles()
    for p in profiles:
        if p["id"] == profile_id:
            p["last_used"] = datetime.now().isoformat()
    save_profiles(profiles)


def get_active_profile_path():
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "active_profile.json")


def get_active_profile() -> dict | None:
    path = get_active_profile_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            ref = json.load(f)
        # Support both new {"profile_id": ...} and legacy full-profile dicts
        profile_id = ref.get("profile_id") or ref.get("id")
        if not profile_id:
            return None
        # Always re-hydrate from profiles.json so the two never drift
        profiles = load_profiles()
        return next((p for p in profiles if p["id"] == profile_id), None)
    except Exception:
        return None


def set_active_profile(profile: dict):
    """Persist a lightweight reference to the active profile."""
    path = get_active_profile_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"profile_id": profile["id"]}, f, indent=2)
    set_last_used(profile["id"])
