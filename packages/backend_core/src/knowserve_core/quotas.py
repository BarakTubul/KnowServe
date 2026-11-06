"""Daily AI-question quotas and the global AI guard (AUTH-36, COST-02, COST-03; M1-10).

M1 builds and tests this mechanism; chat applies it before every LLM call in M4 (CHAT-19).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .identity import IdentityKind
from .web import AppError

QuotaReason = Literal["ok", "user_quota", "global_quota", "kill_switch"]


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    reason: QuotaReason
    limit: int
    used: int
    # Seconds until the next UTC day, for the 429 retry hint.
    retry_after_seconds: int


class QuotaService(Protocol):
    async def consume_ai_question(
        self, session: AsyncSession, *, user_id: uuid.UUID, kind: IdentityKind
    ) -> QuotaDecision:
        """Atomically count one AI question for the user and the global total, or refuse.

        A refusal consumes nothing. The kill switch refuses first (503 ``AI_UNAVAILABLE``), then
        the global quota (503 ``AI_UNAVAILABLE``), then the user's quota (429 ``QUOTA_EXCEEDED``).
        """
        ...


def quota_error(decision: QuotaDecision) -> AppError | None:
    """Map a refusal to the client-visible error, or ``None`` when the question is allowed.

    Graceful degradation (COST-03, INFRA-10): only AI work is refused. The kill switch and the
    global quota give 503 ``AI_UNAVAILABLE``; sign-in, the library and every other route keep
    working. The per-user quota gives 429 ``QUOTA_EXCEEDED`` with a ``Retry-After`` header.
    """
    if decision.allowed:
        return None
    if decision.reason == "user_quota":
        return AppError(
            429,
            "QUOTA_EXCEEDED",
            f"Daily question limit reached. Try again in {decision.retry_after_seconds} seconds.",
            headers={"Retry-After": str(max(1, decision.retry_after_seconds))},
        )
    return AppError(503, "AI_UNAVAILABLE", "AI features are temporarily unavailable")
