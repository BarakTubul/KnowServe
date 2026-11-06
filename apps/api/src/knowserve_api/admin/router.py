"""Admin-only routes (owner: Backend-Identity, M1-05). Contract stub.

``/v1/admin/ping`` only proves the Admin guard (SEC-03): 401 without a session, 403 for registered
and Demo users, 200 for the provisioned Admin. Real Admin features arrive in M3 onward.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import AdminPingResponse, error_responses, not_implemented

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/ping", response_model=AdminPingResponse, responses=error_responses(401, 403))
async def admin_ping() -> AdminPingResponse:
    raise not_implemented()
