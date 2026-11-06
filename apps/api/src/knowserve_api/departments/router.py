"""Departments and the active department (M1-04, AUTH-17, AUTH-20).

Selecting a department grants nothing: it only chooses which department's data the access rules
(M2+) are evaluated for. The five departments are seed data; there is no create/update/delete route.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core import audit
from knowserve_core.identity import Identity
from knowserve_core.models import Department
from knowserve_core.sessions import SessionService, UnknownDepartment
from knowserve_core.web import AppError

from ..auth.deps import get_db, get_identity, get_session_service, require_csrf
from ..schemas import (
    DepartmentsResponse,
    IdentityResponse,
    SetDepartmentRequest,
    error_responses,
)
from .service import build_identity_response, department_out

router = APIRouter(tags=["departments"])


@router.get("/v1/departments", response_model=DepartmentsResponse, responses=error_responses(401))
async def list_departments(
    _: Annotated[Identity, Depends(get_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DepartmentsResponse:
    rows = (await db.scalars(select(Department).order_by(Department.position))).all()
    return DepartmentsResponse(departments=[department_out(row) for row in rows])


@router.put(
    "/v1/session/department",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 422),
)
async def set_active_department(
    body: SetDepartmentRequest,
    identity: Annotated[Identity, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> IdentityResponse:
    """Select or switch the active department (AUTH-17); persisted as the last active one."""
    try:
        await service.set_active_department(
            db,
            session_id=identity.session_id,
            user_id=identity.user_id,
            department_id=body.department_id,
        )
    except UnknownDepartment:
        raise AppError(422, "VALIDATION_ERROR", "Unknown department") from None
    await audit.record(
        db, "department.selected", user_id=identity.user_id, department_id=str(body.department_id)
    )
    await db.commit()
    return await build_identity_response(
        db, replace(identity, active_department_id=body.department_id)
    )
