"""Document status stream, Admin only (M3-05a, ING-07, ING-11, docs/contracts/admin-api.md).

Every message is built from the database: one ``event: status`` on connect, another whenever the
status payload changes, a comment line as a keepalive, and ``event: end`` after a terminal state
(``ready`` or ``failed``) or ``KS_SSE_MAX_SECONDS`` (reason ``timeout``; the client reconnects).
There are no event ids, no stored history and no replay, and connecting never creates or requeues
a job. The document list is the fallback when the stream fails.

The request's database session is released before the first byte is sent, and each tick opens a
short session of its own, so an open stream holds no pool connection while it sleeps.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.documents_access import document_not_found
from knowserve_core.identity import Identity
from knowserve_core.ingestion_contract import (
    SSE_EVENT_END,
    SSE_EVENT_STATUS,
    SSE_KEEPALIVE_COMMENT,
)
from knowserve_core.settings import Settings

from ..auth.deps import get_db, require_admin
from .deps import AdminDocumentId
from .document_views import JobWindows, load_status
from .schemas import DocumentProcessingStatus, admin_error_responses

router = APIRouter(tags=["admin"])

# How often the database is read while a stream is open. Not a setting: it only trades latency
# against load for one Admin, and tests lower it.
POLL_SECONDS = 1.0

_SSE_RESPONSE = {
    200: {
        "description": (
            "Server-sent events for one document. `event: status` carries "
            "DocumentProcessingStatus as JSON, sent on connect and on every change. A comment "
            "line keeps the connection open. `event: end` carries "
            '`{"reason": "terminal" | "timeout"}`; on "timeout" the client reconnects.'
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    }
}

_TERMINAL = frozenset({"ready", "failed"})


def _status_event(payload: str) -> str:
    return f"event: {SSE_EVENT_STATUS}\ndata: {payload}\n\n"


def _end_event(reason: str) -> str:
    return f"event: {SSE_EVENT_END}\ndata: {json.dumps({'reason': reason})}\n\n"


async def status_events(
    factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    windows: JobWindows,
    first: DocumentProcessingStatus,
    *,
    keepalive_seconds: float,
    max_seconds: float,
    poll_seconds: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> AsyncIterator[str]:
    """The text of the stream, starting with ``first`` (the snapshot read at connect)."""
    poll = POLL_SECONDS if poll_seconds is None else poll_seconds
    payload = first.model_dump_json()
    yield _status_event(payload)
    if first.status in _TERMINAL:
        yield _end_event("terminal")
        return
    started = last_sent = monotonic()
    while True:
        remaining = max_seconds - (monotonic() - started)
        if remaining <= 0:
            yield _end_event("timeout")
            return
        await asyncio.sleep(min(poll, remaining))
        current = await load_status(factory, document_id, windows)
        if current is None:
            # Deleted while watching: nothing more will happen to it.
            yield _end_event("terminal")
            return
        now = monotonic()
        current_payload = current.model_dump_json()
        if current_payload != payload:
            payload = current_payload
            last_sent = now
            yield _status_event(payload)
            if current.status in _TERMINAL:
                yield _end_event("terminal")
                return
        elif now - last_sent >= keepalive_seconds:
            last_sent = now
            yield f"{SSE_KEEPALIVE_COMMENT}\n\n"


@router.get(
    "/documents/{document_id}/events",
    response_model=None,
    responses={**_SSE_RESPONSE, **admin_error_responses(401, 403, 404)},
)
async def document_events(
    request: Request,
    _: Annotated[Identity, Depends(require_admin)],
    document_id: AdminDocumentId,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    windows = JobWindows.from_settings(settings)
    # 401, 403 and 404 are real statuses: the snapshot is read before the response starts.
    first = await load_status(factory, document_id, windows)
    if first is None:
        raise document_not_found()
    await db.commit()  # release the connection the session lookup used
    return StreamingResponse(
        status_events(
            factory,
            document_id,
            windows,
            first,
            keepalive_seconds=settings.sse_keepalive_seconds,
            max_seconds=settings.sse_max_seconds,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
