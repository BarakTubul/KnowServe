"""Admin-only routes: the guard proof from M1-05 and the M3 registrar (M3-01).

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
from . import events, imports, manage, upload

router = APIRouter(prefix="/v1/admin", tags=["admin"])
# M3: each slice owns its module (docs/milestones/M3/plan.md section 9). All of them share the
# `/v1/admin` prefix and sit behind `require_admin` or `require_admin_csrf`.
for _slice in (manage, upload, imports, events):
    router.include_router(_slice.router)


@router.get("/ping", response_model=AdminPingResponse, responses=error_responses(401, 403))
async def admin_ping(_: Annotated[Identity, Depends(require_admin)]) -> AdminPingResponse:
    return AdminPingResponse(status="ok")
