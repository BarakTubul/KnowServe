"""Firebase Admin SDK implementation of ``TokenVerifier`` (AUTH-07, AUTH-30, SEC-13, ADR 0004).

What the SDK does for us: signature against Google's keys, issuer, audience and (outside the
emulator) expiry. What this module adds on top, with the injected ``Clock``:

* strict expiry and future-``iat`` checks in both modes (the SDK skips every claim check for
  emulator tokens);
* the freshness rules: ``iat`` within ``KS_AUTH_MAX_AGE_SECONDS`` always, ``auth_time`` within it
  when ``require_fresh``. ``StaleSignIn`` is raised only after every other check passed, so an
  invalid token can never learn about it;
* error mapping: everything wrong with the token is ``InvalidToken``; failing to fetch Google's
  keys is ``VerifierUnavailable`` (fail closed).

Providers and ``email_verified`` are NOT judged here; each endpoint decides (auth-session.md).

Emulator mode. The Admin SDK decides "emulated" from the process environment variable
``FIREBASE_AUTH_EMULATOR_HOST``, not per app. This class therefore sets that variable when (and
only when) ``KS_FIREBASE_AUTH_EMULATOR_HOST`` is configured, refuses to be built when
``KS_ENV=production`` and the emulator host is set, refuses to be built when the raw variable is set
without the setting, and refuses unsigned tokens in real mode even if the variable appears later.
Mixing an emulator verifier and a real one in one process is unsupported.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import firebase_admin
from firebase_admin import auth, credentials
from google.auth import credentials as google_credentials
from google.auth import exceptions as google_exceptions

from .clock import Clock, SystemClock
from .firebase_tokens import InvalidToken, StaleSignIn, VerifiedToken, VerifierUnavailable
from .settings import Settings

logger = logging.getLogger("knowserve.firebase_verifier")

EMULATOR_ENV_VAR = "FIREBASE_AUTH_EMULATOR_HOST"
# Tolerance for the token being issued "in the future" because of clock differences.
CLOCK_SKEW_SECONDS = 5
MAX_TOKEN_LENGTH = 8192
_HTTP_TIMEOUT_SECONDS = 5


class _NoCredential(credentials.Base):
    """Verification needs no Google credential; this avoids Application Default Credentials."""

    def get_credential(self) -> google_credentials.Credentials:
        return google_credentials.AnonymousCredentials()


def _header_alg(token: str) -> str | None:
    """Algorithm named in the (unverified) JWT header; ``None`` when it cannot be read."""
    try:
        segment = token.split(".", 1)[0]
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        header = json.loads(raw)
    except (ValueError, binascii.Error):
        return None
    alg = header.get("alg") if isinstance(header, dict) else None
    return alg if isinstance(alg, str) else None


def _epoch_claim(claims: dict[str, Any], name: str) -> datetime:
    value = claims.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidToken(f"missing or malformed claim: {name}")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise InvalidToken(f"malformed claim: {name}") from exc


class FirebaseTokenVerifier:
    def __init__(self, settings: Settings, clock: Clock | None = None) -> None:
        emulator_host = settings.firebase_auth_emulator_host or None
        if settings.env == "production" and emulator_host:
            raise RuntimeError("the Firebase Auth emulator must not be used when KS_ENV=production")
        if emulator_host is None and os.environ.get(EMULATOR_ENV_VAR):
            raise RuntimeError(
                f"{EMULATOR_ENV_VAR} is set but KS_FIREBASE_AUTH_EMULATOR_HOST is not; "
                "refusing to accept unsigned tokens"
            )
        self._project_id = settings.firebase_project_id
        self._emulator_host = emulator_host
        self._max_age = timedelta(seconds=settings.auth_max_age_seconds)
        self._clock: Clock = clock or SystemClock()
        self._app_name = f"knowserve-verifier-{uuid.uuid4().hex}"
        self._app: firebase_admin.App | None = None
        self._lock = threading.Lock()
        if emulator_host:
            os.environ[EMULATOR_ENV_VAR] = emulator_host

    @property
    def emulated(self) -> bool:
        return self._emulator_host is not None

    def close(self) -> None:
        with self._lock:
            app, self._app = self._app, None
        if app is not None:
            firebase_admin.delete_app(app)

    def _ensure_app(self) -> firebase_admin.App:
        with self._lock:
            if self._app is None:
                if not self._project_id:
                    raise VerifierUnavailable("KS_FIREBASE_PROJECT_ID is not configured")
                self._app = firebase_admin.initialize_app(
                    _NoCredential(),
                    {"projectId": self._project_id, "httpTimeout": _HTTP_TIMEOUT_SECONDS},
                    name=self._app_name,
                )
            return self._app

    async def verify(self, id_token: str, *, require_fresh: bool = True) -> VerifiedToken:
        if not id_token or len(id_token) > MAX_TOKEN_LENGTH:
            raise InvalidToken("empty or oversized token")
        claims = await asyncio.to_thread(self._verify_sync, id_token)
        return self._check_claims(claims, require_fresh)

    def _verify_sync(self, id_token: str) -> dict[str, Any]:
        """Blocking SDK call (key fetch, signature). Runs in a worker thread."""
        if self._emulator_host:
            os.environ[EMULATOR_ENV_VAR] = self._emulator_host
        else:
            if _header_alg(id_token) != "RS256":
                raise InvalidToken("token is not RS256-signed")
            if os.environ.get(EMULATOR_ENV_VAR):
                # Unsigned tokens would be accepted by the SDK. Fail closed for everyone.
                logger.error("%s appeared in a real-mode process", EMULATOR_ENV_VAR)
                raise VerifierUnavailable("emulator mode is not allowed here")
        app = self._ensure_app()
        try:
            claims = auth.verify_id_token(id_token, app=app, clock_skew_seconds=CLOCK_SKEW_SECONDS)
        except auth.InvalidIdTokenError as exc:  # includes expired and malformed tokens
            raise InvalidToken(type(exc).__name__) from exc
        except (auth.CertificateFetchError, google_exceptions.TransportError, OSError) as exc:
            logger.warning("firebase key fetch failed: %s", type(exc).__name__)
            raise VerifierUnavailable("could not fetch Firebase signing keys") from exc
        except ValueError as exc:  # empty token or an unusable configuration
            raise InvalidToken(type(exc).__name__) from exc
        except Exception as exc:
            logger.warning("unexpected token verification error: %s", type(exc).__name__)
            raise InvalidToken(type(exc).__name__) from exc
        if not isinstance(claims, dict):
            raise InvalidToken("unexpected claims")
        return claims

    def _check_claims(self, claims: dict[str, Any], require_fresh: bool) -> VerifiedToken:
        now = self._clock.now()
        skew = timedelta(seconds=CLOCK_SKEW_SECONDS)
        expires = _epoch_claim(claims, "exp")
        issued_at = _epoch_claim(claims, "iat")
        auth_time = _epoch_claim(claims, "auth_time")
        uid = claims.get("uid") or claims.get("sub")
        firebase = claims.get("firebase")
        provider = firebase.get("sign_in_provider") if isinstance(firebase, dict) else None
        if not isinstance(uid, str) or not uid or not isinstance(provider, str) or not provider:
            raise InvalidToken("missing uid or sign-in provider")
        if expires <= now:
            raise InvalidToken("token expired")
        if issued_at > now + skew or auth_time > now + skew:
            raise InvalidToken("token issued in the future")
        email = claims.get("email")
        name = claims.get("name")
        verified = VerifiedToken(
            uid=uid,
            email=email if isinstance(email, str) else None,
            email_verified=claims.get("email_verified") is True,
            sign_in_provider=provider,
            auth_time=auth_time,
            issued_at=issued_at,
            name=name if isinstance(name, str) else None,
        )
        # Every other check has passed; only now may the caller learn the token is merely stale.
        if now - issued_at > self._max_age:
            raise StaleSignIn("token was issued outside the freshness window")
        if require_fresh and now - auth_time > self._max_age:
            raise StaleSignIn("sign-in is outside the freshness window")
        return verified
