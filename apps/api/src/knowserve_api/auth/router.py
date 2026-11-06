"""Auth routes (owner: Backend-Auth, M1-02a/02b). M1-01 provides stubs that fix the contract.

Error codes (docs/contracts/auth-session.md): 401 UNAUTHENTICATED / REAUTH_REQUIRED, 403
EMAIL_NOT_VERIFIED / CSRF_INVALID / ORIGIN_INVALID, 409 CONFLICT, 429 RATE_LIMITED, 503
DEPENDENCY_UNAVAILABLE.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..schemas import (
    IdentityResponse,
    IdTokenRequest,
    RevokeAllResponse,
    error_responses,
    not_implemented,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post(
    "/session",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 429, 503),
)
async def create_session(body: IdTokenRequest, response: Response) -> IdentityResponse:
    """Verify a fresh Firebase ID token (password or Google) and start a KnowServe session."""
    raise not_implemented()


@router.post(
    "/convert",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 409, 503),
)
async def convert_demo(body: IdTokenRequest, response: Response) -> IdentityResponse:
    """Convert the current Demo identity to Registered after a successful credential link."""
    raise not_implemented()


@router.post("/logout", status_code=204, responses=error_responses(401, 403))
async def logout() -> Response:
    raise not_implemented()


@router.get("/me", response_model=IdentityResponse, responses=error_responses(401))
async def me() -> IdentityResponse:
    raise not_implemented()


@router.post(
    "/sessions/revoke-all",
    response_model=RevokeAllResponse,
    responses=error_responses(401, 403),
)
async def revoke_all_sessions() -> RevokeAllResponse:
    """Sign out everywhere: revoke every KnowServe session of the current user (AUTH-33)."""
    raise not_implemented()
