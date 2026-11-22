"""
AuthManager — user authentication with pluggable providers.

Providers:
  LocalAuthProvider   — users.json on device (current, offline)
  GoogleAuthProvider  — OAuth2 via browser + localhost callback
  AiimsAuthProvider   — AIIMS server REST API (stub, not yet live)

All providers return a unified User dict:
  { "id": str, "identifier": str, "name": str, "provider": str }

Passwords are stored as bcrypt hashes (cost factor 12).
Legacy SHA-256 hashes (64-char hex) are automatically migrated on
successful login — no action needed from existing users.
"""
import os
import re
import json
import uuid
import hashlib
from abc import ABC, abstractmethod
from typing import Optional


# ── Email validation (L3) ─────────────────────────────────────────────────────

# RFC-5322-inspired pattern — catches the vast majority of invalid addresses
# without being so strict it rejects valid ones.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

def validate_email(email: str) -> tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    error_message is empty string when valid.
    """
    email = email.strip()
    if not email:
        return False, "Email address is required."
    if len(email) > 254:
        return False, "Email address is too long."
    if not _EMAIL_RE.match(email):
        return False, "Please enter a valid email address (e.g. name@clinic.org)."
    return True, ""


# ── Password hashing — bcrypt (L2) ───────────────────────────────────────────

def _bcrypt_hash(password: str) -> str:
    """Hash password with bcrypt (cost 12). Returns the hash as a utf-8 string."""
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _bcrypt_verify(password: str, hashed: str) -> bool:
    import bcrypt
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _is_sha256(s: str) -> bool:
    """Detect legacy SHA-256 hash: 64 lowercase hex chars."""
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def _is_bcrypt(s: str) -> bool:
    """Detect bcrypt hash: starts with '$2b$' or '$2a$'."""
    return s.startswith(("$2b$", "$2a$"))


def _sha256_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _verify_password(password: str, stored: str) -> tuple[bool, bool]:
    """
    Verify a password against its stored hash.
    Returns (matches, needs_rehash_to_bcrypt).
    Legacy SHA-256 hashes are verified and flagged for upgrade.
    """
    if _is_bcrypt(stored):
        return _bcrypt_verify(password, stored), False
    elif _is_sha256(stored):
        # Legacy SHA-256 — verify then flag for upgrade
        return _sha256_hash(password) == stored, True
    else:
        # Old plaintext (very old accounts)
        return stored == password, True


# ── Abstract provider interface ───────────────────────────────────────────────

class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, identifier: str, password: str) -> Optional[dict]:
        """Return user dict on success, None on failure."""

    @abstractmethod
    def register(self, identifier: str, password: str, name: str) -> Optional[dict]:
        """Create new user. Return user dict or None if identifier taken."""


# ── Local provider ────────────────────────────────────────────────────────────

MAX_ACCOUNTS = 3     # §6: per-install account cap


def _get_users_path() -> str:
    from core.paths import get_data_dir
    return os.path.join(get_data_dir(), "users.json")


def _load_users() -> list[dict]:
    path = _get_users_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_users(users: list[dict]):
    path = _get_users_path()
    tmp  = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def list_accounts() -> list[dict]:
    """Registered local accounts (no passwords) — for the login manager."""
    return [{"id": u.get("id"), "identifier": u.get("identifier", ""),
             "name": u.get("name", "")} for u in _load_users()]


def delete_user(user_id: str) -> bool:
    """Permanently remove a login account. Returns True if one was removed."""
    users = _load_users()
    remaining = [u for u in users if u.get("id") != user_id]
    if len(remaining) == len(users):
        return False
    _save_users(remaining)
    return True


def _rehash_user(user_id: str, new_hash: str):
    """L2: Upgrade legacy SHA-256/plaintext hash to bcrypt on successful login."""
    users = _load_users()
    for u in users:
        if u["id"] == user_id:
            u["password"] = new_hash
            break
    _save_users(users)


class LocalAuthProvider(AuthProvider):
    def authenticate(self, identifier: str, password: str) -> Optional[dict]:
        users = _load_users()
        identifier = identifier.strip().lower()

        for user in users:
            if user.get("identifier", "").strip().lower() != identifier:
                continue
            stored = user.get("password", "")
            matches, needs_upgrade = _verify_password(password, stored)

            if matches:
                # L2: transparently upgrade legacy hash to bcrypt
                if needs_upgrade:
                    _rehash_user(user["id"], _bcrypt_hash(password))
                return {
                    "id":         user["id"],
                    "identifier": user["identifier"],
                    "name":       user.get("name", ""),
                    "provider":   "local",
                }
        # Distinguish "no such email" from "wrong password" for U5 error messages
        emails = [u.get("identifier", "").strip().lower() for u in users]
        if identifier not in emails:
            raise RuntimeError(f"No user found for {identifier}")
        raise RuntimeError("Invalid password")

    def register(self, identifier: str, password: str, name: str) -> Optional[dict]:
        # L3: validate email before writing anything
        valid, err = validate_email(identifier)
        if not valid:
            raise RuntimeError(err)

        identifier = identifier.strip().lower()
        users = _load_users()
        if any(u.get("identifier", "").strip().lower() == identifier for u in users):
            raise RuntimeError(f"Email already registered: {identifier}")
        # §6: NO hard account cap — this is a home device, the cap only ever
        # got in the way. Accounts are the cloud-sync anchor, not a rationed
        # resource. (Clean up unused ones from Settings → Delete Account.)

        user = {
            "id":         str(uuid.uuid4()),
            "identifier": identifier,
            "password":   _bcrypt_hash(password),   # L2: bcrypt from day one
            "name":       name.strip(),
            "provider":   "local",
        }
        users.append(user)
        _save_users(users)
        return {k: v for k, v in user.items() if k != "password"}

    def change_password(self, identifier: str, old_password: str, new_password: str) -> bool:
        """
        F1: Change a user's password. Verifies old_password first.
        Raises RuntimeError with a user-friendly message on failure.
        Returns True on success.
        """
        if len(new_password) < 6:
            raise RuntimeError("New password must be at least 6 characters.")

        users = _load_users()
        identifier = identifier.strip().lower()
        for user in users:
            if user.get("identifier", "").strip().lower() != identifier:
                continue
            stored = user.get("password", "")
            matches, _ = _verify_password(old_password, stored)
            if not matches:
                raise RuntimeError("Current password is incorrect.")
            user["password"] = _bcrypt_hash(new_password)
            _save_users(users)
            return True
        raise RuntimeError("Account not found.")


# ── Google OAuth provider (see core/google_oauth.py for the flow) ─────────────

class GoogleAuthProvider(AuthProvider):
    def authenticate(self, identifier: str = "", password: str = "") -> Optional[dict]:
        """Trigger browser-based OAuth flow. identifier/password unused."""
        from core.google_oauth import run_google_oauth
        return run_google_oauth()

    def register(self, identifier: str = "", password: str = "", name: str = "") -> Optional[dict]:
        """Google accounts don't need a separate registration step."""
        return self.authenticate()


# ── AIIMS server provider (stub — not yet live) ───────────────────────────────

class AiimsAuthProvider(AuthProvider):
    """
    Placeholder for AIIMS hospital server authentication.
    Swap in when the AIIMS API is ready. Expected API contract:
      POST /api/v1/auth/login  { "email": ..., "password": ... }
      → { "token": ..., "user": { "id", "name", "email" } }
    """
    AIIMS_BASE_URL = "https://aiims-api.example.com"   # TODO: replace with real URL

    def authenticate(self, identifier: str, password: str) -> Optional[dict]:
        raise NotImplementedError("AIIMS server auth not yet live")

    def register(self, identifier: str, password: str, name: str) -> Optional[dict]:
        raise NotImplementedError("AIIMS server auth not yet live")


# ── Convenience functions (backwards-compatible) ──────────────────────────────

_local = LocalAuthProvider()

def authenticate(identifier: str, password: str) -> Optional[dict]:
    return _local.authenticate(identifier, password)

def register_user(identifier: str, password: str, name: str) -> Optional[dict]:
    return _local.register(identifier, password, name)
