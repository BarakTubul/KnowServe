"""Google ID-token verification shared by the Worker dispatcher and the API operator routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

OidcVerifier = Callable[[str, str], dict[str, Any]]


def google_oidc_verifier(token: str, audience: str) -> dict[str, Any]:
    """Verify a Google-signed ID token. Blocking; BLOCKED live (no real token available)."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)  # type: ignore[no-untyped-call]
