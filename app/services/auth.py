"""Demo authentication: hashed passwords, signed session cookies, and roles.

Built on the standard library only (hashlib, hmac), so there's nothing extra to
install. Good enough for a demo; for production, use a managed identity service
such as Amazon Cognito.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from functools import lru_cache

from app.services.storage import Storage

SESSION_COOKIE = "cyanguard_session"

# Lowest to highest. Each role can do everything the roles before it can.
ROLES = ("analyst", "compliance", "admin")
ROLE_LABELS = {"analyst": "Analyst", "compliance": "Compliance Officer", "admin": "Admin"}

# Created on first login when the users collection is empty: (username, display name, role).
DEMO_USERS = (
    ("analyst", "Demo Analyst", "analyst"),
    ("compliance", "Demo Compliance Officer", "compliance"),
    ("admin", "Demo Admin", "admin"),
)

PBKDF2_ITERATIONS = 200_000


# --- Passwords ---

def hash_password(password: str, *, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


@lru_cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_hex(8))


def verify_password(password: str, stored: str | None) -> bool:
    """Check a password against a stored hash in constant time.

    An unknown user (stored=None) still runs a full hash, so response time doesn't
    reveal whether a username exists.
    """
    _algorithm, iterations, salt_hex, digest_hex =(stored or _dummy_hash()).split("$")
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
    return stored is not None and hmac.compare_digest(candidate.hex(), digest_hex)


# --- Roles ---

def role_at_least(role: str, minimum: str) -> bool:
    return role in ROLES and ROLES.index(role) >= ROLES.index(minimum)


def public_user(user: dict) -> dict:
    """The fields that are safe to send to the browser."""
    return {
        "id": user["id"],
        "name": user["name"],
        "role": user["role"],
        "role_label": ROLE_LABELS.get(user["role"], user["role"]),
    }


# --- Sessions ---

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def sign_session(user_id: str, secret: str, ttl_seconds: int, *, now: float | None = None) -> str:
    """Create a tamper-proof session token: base64(json payload) + "." + HMAC signature."""
    expires = int((now or time.time()) + ttl_seconds)
    payload = _b64(json.dumps({"sub": user_id, "exp": expires}).encode())
    return f"{payload}.{_signature(payload, secret)}"


def read_session(token: str, secret: str, *, now: float | None = None) -> str | None:
    """Return the user ID from a valid, unexpired token, or None."""
    try:
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _signature(payload, secret)):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, TypeError):
        return None
    if data.get("exp", 0) < (now or time.time()):
        return None
    return data.get("sub")


# --- Demo accounts ---

def seed_demo_users(users: Storage, password: str) -> bool:
    """Create the demo accounts if no users exist yet. Returns True if it created them."""
    if users.list():
        return False
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for username, name, role in DEMO_USERS:
        users.put({
            "id": username,
            "name": name,
            "role": role,
            "password_hash": hash_password(password),
            "created_at": created_at,
        })
    return True
