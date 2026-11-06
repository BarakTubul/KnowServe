"""Internal, non-HTTP user operations (AUTH-33, OPEN-26 O2). No route calls these.

``disable_user`` blocks a user: it sets ``users.disabled_at``, revokes every live session and
writes an audit event. A disabled user fails ``SessionService.lookup_by_token`` and cannot get a
new session from the exchange. It is the only supported way to disable a user in M1 (there is no
user-administration feature).
"""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from . import audit
from .clock import Clock, SystemClock
from .models import User
from .sessions import SessionService


async def disable_user(
    session: AsyncSession, user_id: uuid.UUID, *, clock: Clock | None = None
) -> bool:
    """Disable ``user_id`` and revoke its sessions in one transaction (committed here).

    Returns ``False`` when the user does not exist or was already disabled (nothing changes).
    """
    the_clock = clock or SystemClock()
    now = the_clock.now()
    result = await session.execute(
        update(User)
        .where(User.id == user_id, User.disabled_at.is_(None))
        .values(disabled_at=now, updated_at=now)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        await session.rollback()
        return False
    revoked = await SessionService(1, the_clock).revoke_all_for_user(session, user_id)
    await audit.record(session, "auth.user.disabled", user_id=user_id, revoked_sessions=revoked)
    await session.commit()
    return True
