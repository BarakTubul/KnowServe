"""Opaque token helpers (AUTH-06, AUTH-14). Plaintext tokens are never stored or logged."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_session_token() -> str:
    """256 bits of CSPRNG output, URL-safe. This is the cookie value."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The only form of a session token that reaches PostgreSQL."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_secret() -> str:
    """Per-session CSRF token (AUTH-14). Stored on the session row, returned to its owner."""
    return secrets.token_urlsafe(32)


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
