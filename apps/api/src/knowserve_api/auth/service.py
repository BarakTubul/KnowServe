"""Session exchange and Demo conversion logic (AUTH-30, AUTH-32, AUTH-34), M1-02b.

Everything here runs inside the caller's transaction and never commits, except ``deny`` (which
commits the audit entry before the caller raises). Callers commit BEFORE building the response.

Conversion contract (M1-11 security review): the ``users`` row is locked with ``SELECT ... FOR
UPDATE`` first, kind flips ``demo -> registered`` in one UPDATE guarded by ``kind = 'demo'``, and a
missing row means Demo cleanup won the race: the convert endpoint answers 401 and never recreates
the user. Email is never used to merge or link accounts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import NoReturn

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core import audit
from knowserve_core.firebase_tokens import VerifiedToken
from knowserve_core.identity import Identity
from knowserve_core.models import Department, User
from knowserve_core.web import AppError

from ..schemas import DepartmentOut, IdentityResponse
from .deps import unauthenticated

ALLOWED_PROVIDERS = frozenset({"password", "google.com"})


class EmailTaken(Exception):
    """Another users row already owns the email."""


def normalize_email(email: str | None) -> str | None:
    cleaned = (email or "").strip().lower()
    return cleaned or None


async def deny(
    db: AsyncSession, reason: str, error: AppError, *, user_id: uuid.UUID | None = None
) -> NoReturn:
    """Audit the refusal (committed, since the caller is about to raise) and raise ``error``."""
    await db.rollback()
    await audit.record(db, "auth.session.denied", user_id=user_id, reason=reason)
    await db.commit()
    raise error


async def lock_user_by_uid(db: AsyncSession, uid: str) -> User | None:
    stmt = select(User).where(User.firebase_uid == uid).with_for_update()
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()


async def email_owner(db: AsyncSession, email: str) -> uuid.UUID | None:
    return await db.scalar(select(User.id).where(User.email == email))


async def create_registered(
    db: AsyncSession, uid: str, email: str, name: str | None
) -> User | None:
    """Insert a registered user. ``None`` if the uid or the email was taken concurrently."""
    user = User(firebase_uid=uid, kind="registered", email=email, display_name=name)
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        return None
    return user


async def convert_locked_demo_user(
    db: AsyncSession, user: User, email: str, name: str | None, now: datetime
) -> None:
    """Flip a locked Demo row to registered. Raises ``EmailTaken`` on a collision.

    Keeps ``id``, ``firebase_uid``, ``created_at`` and ``last_active_department_id``; never sets
    kind back to demo.
    """
    if await email_owner(db, email) not in (None, user.id):
        raise EmailTaken
    values: dict[str, object] = {
        "kind": "registered",
        "email": email,
        "converted_at": now,
        "updated_at": now,
    }
    if name and not user.display_name:
        values["display_name"] = name
    try:
        async with db.begin_nested():
            result = await db.execute(
                update(User).where(User.id == user.id, User.kind == "demo").values(**values)
            )
    except IntegrityError:
        raise EmailTaken from None
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise EmailTaken  # unreachable under the row lock; fail closed rather than half-convert
    await db.refresh(user)


async def identity_response(db: AsyncSession, identity: Identity) -> IdentityResponse:
    department = None
    if identity.active_department_id is not None:
        row = await db.get(Department, identity.active_department_id)
        if row is not None:
            department = DepartmentOut(id=row.id, slug=row.slug, name=row.name)
    return IdentityResponse(
        kind=identity.kind,
        user_id=identity.user_id,
        email=identity.email,
        display_name=identity.display_name,
        sign_in_provider=identity.sign_in_provider,  # type: ignore[arg-type]
        active_department=department,
        expires_at=identity.expires_at,
        csrf_token=identity.csrf_token,
    )


def require_verified(verified: VerifiedToken) -> str:
    """Endpoint rules shared by /session and /convert; returns the normalized email."""
    if verified.sign_in_provider not in ALLOWED_PROVIDERS:
        raise unauthenticated()
    email = normalize_email(verified.email)
    if email is None:
        raise unauthenticated()
    if not verified.email_verified:
        raise AppError(403, "EMAIL_NOT_VERIFIED", "Verify your email address to continue")
    return email
