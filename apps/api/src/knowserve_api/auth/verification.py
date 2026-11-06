"""Maps verifier outcomes to the contract's HTTP errors (AUTH-07, AUTH-30, SEC-13).

Every invalid-token cause yields the same 401 body, so a caller cannot tell a forged token from an
expired one. Only a token that passed every other check can produce ``REAUTH_REQUIRED``.
"""

from __future__ import annotations

from knowserve_core.firebase_tokens import (
    InvalidToken,
    StaleSignIn,
    TokenVerifier,
    VerifiedToken,
    VerifierUnavailable,
)
from knowserve_core.web import AppError


async def verify_id_token_or_raise(
    verifier: TokenVerifier, id_token: str, *, require_fresh: bool = True
) -> VerifiedToken:
    try:
        return await verifier.verify(id_token, require_fresh=require_fresh)
    except InvalidToken:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required") from None
    except StaleSignIn:
        raise AppError(401, "REAUTH_REQUIRED", "Sign in again to continue") from None
    except VerifierUnavailable:
        raise AppError(503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable") from None
