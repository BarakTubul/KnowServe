"""Opaque server-side sessions (AUTH-06, AUTH-10, ADR 0004).

* ``create_session`` stores only ``sha256(token)``; the plaintext token is returned once.
* ``expires_at`` is absolute (``created_at + KS_SESSION_TTL_SECONDS``). Nothing here ever extends
  it or writes a last-seen value; there is no refresh operation.
* ``lookup_by_token`` is a read-only query: unknown, expired, revoked sessions and disabled users
  all yield ``None`` (the API answers the same generic 401 for each).

Methods add to the caller's ``AsyncSession`` and flush; the caller owns the transaction and
commits (session creation happens together with the ``users`` row and the audit event).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .clock import Clock, SystemClock
from .identity import Identity
from .models import Department, Session, User
from .security import hash_token, new_csrf_secret, new_session_token


class UnknownDepartment(Exception):
    """The department id does not exist."""


class SessionService:
    def __init__(self, ttl_seconds: int, clock: Clock | None = None) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock: Clock = clock or SystemClock()

    async def create_session(
        self,
        db: AsyncSession,
        user: User,
        provider: str,
        department_id: uuid.UUID | None = None,
    ) -> tuple[str, Session]:
        """Create a new session (new id, new token, new CSRF secret). Returns ``(token, row)``."""
        token = new_session_token()
        now = self._clock.now()
        row = Session(
            id=uuid.uuid4(),
            token_hash=hash_token(token),
            user_id=user.id,
            sign_in_provider=provider,
            active_department_id=department_id,
            csrf_secret=new_csrf_secret(),
            created_at=now,
            expires_at=now + self._ttl,
        )
        db.add(row)
        await db.flush()
        return token, row

    async def lookup_by_token(self, db: AsyncSession, token: str) -> Identity | None:
        """Resolve a cookie value to an identity, or ``None``. Never writes."""
        if not token:
            return None
        now = self._clock.now()
        stmt = (
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(
                Session.token_hash == hash_token(token),
                Session.revoked_at.is_(None),
                Session.expires_at > now,
                User.disabled_at.is_(None),
            )
        )
        found = (await db.execute(stmt)).first()
        if found is None:
            return None
        row, user = found
        return Identity(
            kind=user.kind,  # type: ignore[arg-type]  # constrained by users_kind
            user_id=user.id,
            firebase_uid=user.firebase_uid,
            session_id=row.id,
            sign_in_provider=row.sign_in_provider,
            email=user.email,
            display_name=user.display_name,
            active_department_id=row.active_department_id,
            expires_at=row.expires_at,
            csrf_token=row.csrf_secret,
        )

    async def revoke_session(self, db: AsyncSession, session_id: uuid.UUID) -> bool:
        """Revoke one session. ``False`` if it was already revoked or does not exist."""
        result = await db.execute(
            update(Session)
            .where(Session.id == session_id, Session.revoked_at.is_(None))
            .values(revoked_at=self._clock.now())
        )
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def revoke_all_for_user(self, db: AsyncSession, user_id: uuid.UUID) -> int:
        """Revoke every live session of the user ("sign out everywhere"). Returns how many."""
        now = self._clock.now()
        result = await db.execute(
            update(Session)
            .where(
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
            )
            .values(revoked_at=now)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def set_active_department(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        department_id: uuid.UUID,
    ) -> None:
        """Select the session's department and remember it as the user's last active one."""
        exists = await db.scalar(select(Department.id).where(Department.id == department_id))
        if exists is None:
            raise UnknownDepartment(str(department_id))
        await db.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(active_department_id=department_id)
        )
        await db.execute(
            update(User).where(User.id == user_id).values(last_active_department_id=department_id)
        )
