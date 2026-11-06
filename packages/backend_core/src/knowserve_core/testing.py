"""Test helpers shared by every slice (M1-01 fixtures). Not used by production code paths.

``mint_emulator_token`` builds an unsigned Firebase-style ID token like the Firebase Auth Emulator
issues (``alg: none``). The real verifier accepts such tokens only when ``KS_ENV`` is not
``production`` and ``KS_FIREBASE_AUTH_EMULATOR_HOST`` is set, so integration tests exercise the
real verification path without the network (AUTH-30).
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

DEFAULT_PROJECT_ID = "demo-knowserve"


def _b64(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def mint_emulator_token(
    uid: str,
    *,
    email: str | None = None,
    email_verified: bool = False,
    provider: str = "password",
    project_id: str = DEFAULT_PROJECT_ID,
    auth_time: datetime | None = None,
    issued_at: datetime | None = None,
    lifetime: timedelta = timedelta(hours=1),
    name: str | None = None,
) -> str:
    """Return an unsigned ID token; ``provider`` is password, google.com or anonymous."""
    now = datetime.now(UTC)
    iat = issued_at or now
    auth = auth_time or iat
    identities: dict[str, list[str]] = {}
    if email and provider == "password":
        identities["email"] = [email]
    if email and provider == "google.com":
        identities["google.com"] = [f"google-{uid}"]
        identities["email"] = [email]
    payload: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{project_id}",
        "aud": project_id,
        "auth_time": int(auth.timestamp()),
        "user_id": uid,
        "sub": uid,
        "iat": int(iat.timestamp()),
        "exp": int((iat + lifetime).timestamp()),
        "firebase": {"identities": identities, "sign_in_provider": provider},
    }
    if email:
        payload["email"] = email
        payload["email_verified"] = email_verified
    if name:
        payload["name"] = name
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."
