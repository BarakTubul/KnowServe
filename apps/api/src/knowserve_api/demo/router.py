"""Try Demo (owner: Backend-Identity, M1-04). M1-01 provides the contract stub."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ..schemas import IdentityResponse, IdTokenRequest, error_responses, not_implemented

router = APIRouter(prefix="/v1/demo", tags=["demo"])


@router.post(
    "/start",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 429, 503),
)
async def start_demo(body: IdTokenRequest, response: Response) -> IdentityResponse:
    """Start a Demo session from a fresh Firebase anonymous ID token (AUTH-16).

    401 ``DEMO_EXPIRED`` when this Demo identity is past its 24 hours.
    """
    raise not_implemented()
