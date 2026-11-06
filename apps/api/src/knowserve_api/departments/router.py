"""Departments and the active department (owner: Backend-Identity, M1-04). Contract stubs."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import (
    DepartmentsResponse,
    IdentityResponse,
    SetDepartmentRequest,
    error_responses,
    not_implemented,
)

router = APIRouter(tags=["departments"])


@router.get("/v1/departments", response_model=DepartmentsResponse, responses=error_responses(401))
async def list_departments() -> DepartmentsResponse:
    raise not_implemented()


@router.put(
    "/v1/session/department",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 422),
)
async def set_active_department(body: SetDepartmentRequest) -> IdentityResponse:
    """Select or switch the active department (AUTH-17); persisted as the last active one."""
    raise not_implemented()
