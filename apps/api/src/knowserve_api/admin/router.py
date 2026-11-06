"""Admin-only routes (M1-05). Real Admin features arrive in M3 onward.

``/v1/admin/ping`` only proves the Admin guard (SEC-03): 401 without a session, 403 for registered
and Demo users, 200 for the provisioned Admin. There is deliberately no route that creates or
elevates an Admin (AUTH-04); provisioning is the ``knowserve_api.admin_seed`` command.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from knowserve_core.identity import Identity

from ..auth.deps import require_admin
from ..schemas import AdminPingResponse, error_responses

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/ping", response_model=AdminPingResponse, responses=error_responses(401, 403))
async def admin_ping(_: Annotated[Identity, Depends(require_admin)]) -> AdminPingResponse:
    return AdminPingResponse(status="ok")
