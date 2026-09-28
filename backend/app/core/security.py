"""Passwords and random tokens.

- Passwords: Argon2id (argon2-cffi defaults follow the RFC 9106 recommendations).
- Tokens (session cookies, email links): 32 random bytes, URL-safe. Only the SHA-256
  hash is stored, so a copy of the database can't be used to sign in or reset a password.
"""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Verifying against this when the user does not exist keeps response times equal,
# so attackers can't find registered emails by timing the login endpoint.
_DUMMY_HASH = _hasher.hash("not-a-real-password-just-for-timing")


def hash_password(password: str) -> str:
    """Hash a password for storage."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """True if the password matches. Safe to call with no hash (runs a dummy check)."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(password_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older settings (rehash after a good login)."""
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    """A random, URL-safe token for cookies and email links."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a token (what the database stores)."""
    return hashlib.sha256(token.encode()).hexdigest()


def sign_data(data: dict[str, Any], secret: str, *, max_age_seconds: int) -> str:
    """A tamper-proof, expiring, URL-safe string that carries `data` (JSON).

    Only for short-lived links we hand out ourselves (e.g. the local pretend checkout).
    The content is readable, so never put secrets in it.
    """
    payload = {**data, "exp": int(time.time()) + max_age_seconds}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{body.decode().rstrip('=')}.{mac}"


def unsign_data(token: str, secret: str) -> dict[str, Any] | None:
    """The data from `sign_data`, or None if the string was changed or has expired."""
    body, _, mac = token.rpartition(".")
    if not body:
        return None
    padded = body + "=" * (-len(body) % 4)
    expected = hmac.new(secret.encode(), padded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(data, dict) or int(data.get("exp", 0)) < time.time():
        return None
    return data
