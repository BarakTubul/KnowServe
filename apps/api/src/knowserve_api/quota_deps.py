"""FastAPI dependency that counts one AI question for the caller (AUTH-36, COST-02/03; M1-10).

Chat adds ``Depends(consume_ai_question)`` before any LLM call in M4. Only AI work is refused:
sign-in, the library and every other route are untouched by the kill switch or the quotas.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_api.auth.deps import get_clock, get_db, get_identity, get_settings_dep
from knowserve_core.clock import Clock
from knowserve_core.identity import Identity
from knowserve_core.quotas import QuotaDecision, QuotaService, quota_error
from knowserve_core.quotas_pg import PostgresQuotaService
from knowserve_core.settings import Settings


def get_quota_service(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> QuotaService:
    service = getattr(request.app.state, "quota_service", None)
    if service is None:
        service = PostgresQuotaService(settings, clock)
        request.app.state.quota_service = service
    return service


async def consume_ai_question(
    identity: Annotated[Identity, Depends(get_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
    quotas: Annotated[QuotaService, Depends(get_quota_service)],
) -> QuotaDecision:
    """Count one question or raise 429 ``QUOTA_EXCEEDED`` / 503 ``AI_UNAVAILABLE``."""
    decision = await quotas.consume_ai_question(db, user_id=identity.user_id, kind=identity.kind)
    error = quota_error(decision)
    if error is not None:
        raise error
    return decision
