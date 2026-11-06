"""Firebase ID-token verification interface (AUTH-30, ADR 0004).

The real verifier (Firebase Admin SDK, emulator-aware, refused in production) is M1-02a. Everything
else depends only on this interface, so slices can be tested with ``FakeTokenVerifier``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class InvalidToken(Exception):
    """Signature, issuer, audience, expiry, format or provider problems. Maps to the generic 401."""


class StaleSignIn(Exception):
    """A valid token whose sign-in is older than the freshness window. Maps to 401 REAUTH_REQUIRED.

    Raised only after every other check passed, so an invalid token never learns about it.
    """


class VerifierUnavailable(Exception):
    """Firebase keys could not be fetched and none are cached. Fails closed with 503 (SEC-13)."""


@dataclass(frozen=True)
class VerifiedToken:
    uid: str
    email: str | None
    email_verified: bool
    sign_in_provider: str
    auth_time: datetime
    issued_at: datetime
    name: str | None = None


class TokenVerifier(Protocol):
    async def verify(self, id_token: str, *, require_fresh: bool = True) -> VerifiedToken:
        """Verify ``id_token``.

        With ``require_fresh`` the sign-in (``auth_time``) must be within the freshness window,
        otherwise ``StaleSignIn``. Conversion passes ``require_fresh=False`` and relies on the Demo
        session plus a recently issued token (``issued_at`` within the window), which the verifier
        enforces in both modes.
        """
        ...


class FakeTokenVerifier:
    """In-memory verifier for unit tests: register tokens, get the result or the error."""

    def __init__(self) -> None:
        self._tokens: dict[str, VerifiedToken | Exception] = {}

    def add(self, id_token: str, result: VerifiedToken | Exception) -> None:
        self._tokens[id_token] = result

    async def verify(self, id_token: str, *, require_fresh: bool = True) -> VerifiedToken:
        result = self._tokens.get(id_token)
        if result is None:
            raise InvalidToken("unknown token")
        if isinstance(result, Exception):
            raise result
        return result
