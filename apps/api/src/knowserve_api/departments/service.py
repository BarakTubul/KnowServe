"""Shared helpers for identity answers that include the active department (M1-04)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core.identity import Identity
from knowserve_core.models import Department

from ..schemas import DepartmentOut, IdentityResponse


def department_out(row: Department) -> DepartmentOut:
    return DepartmentOut(id=row.id, slug=row.slug, name=row.name)


async def load_department(
    db: AsyncSession, department_id: uuid.UUID | None
) -> DepartmentOut | None:
    if department_id is None:
        return None
    row = await db.scalar(select(Department).where(Department.id == department_id))
    return department_out(row) if row is not None else None


async def build_identity_response(db: AsyncSession, identity: Identity) -> IdentityResponse:
    return IdentityResponse(
        kind=identity.kind,
        user_id=identity.user_id,
        email=identity.email,
        display_name=identity.display_name,
        sign_in_provider=identity.sign_in_provider,  # type: ignore[arg-type]  # DB-constrained
        active_department=await load_department(db, identity.active_department_id),
        expires_at=identity.expires_at,
        csrf_token=identity.csrf_token,
    )
