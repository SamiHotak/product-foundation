"""Passwords and random tokens.

- Passwords: Argon2id (argon2-cffi defaults follow the RFC 9106 recommendations).
- Tokens (session cookies, email links): 32 random bytes, URL-safe. Only the SHA-256
  hash is stored, so a copy of the database can't be used to sign in or reset a password.
"""

import hashlib
import secrets

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
