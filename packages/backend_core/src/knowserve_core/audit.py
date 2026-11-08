"""Audit trail writer (AUTH-21, MON-04, MON-05).

``record`` is the only way slices write ``audit_events``. Details pass through the same redaction
as the logs, so a token, cookie or CSRF value can never be stored even by mistake. Only counts and
ids belong in ``details``.

No client address is ever written (SEC-18, OPEN-28 Q9): ``record`` has no ``ip`` parameter and
``audit_events.ip`` stays NULL. The column remains only so the running revision keeps reading the
model.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from . import request_context
from .logging import redact
from .models import AuditEvent

logger = logging.getLogger("knowserve.audit")


async def record(
    session: AsyncSession,
    event: str,
    *,
    user_id: uuid.UUID | None = None,
    **details: Any,
) -> None:
    """Add an audit row to the caller's transaction (it commits or rolls back with it)."""
    safe: dict[str, Any] = redact(details)
    request_id = request_context.get_request_id()
    session.add(AuditEvent(event=event, user_id=user_id, request_id=request_id, details=safe))
    await session.flush()
    logger.info(
        "audit event",
        extra={"audit_event": event, "user_id": str(user_id) if user_id else None, **safe},
    )
