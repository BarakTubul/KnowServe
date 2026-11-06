"""Daily AI-question quotas and the global AI guard (AUTH-36, COST-02, COST-03; M1-10).

M1 builds and tests this mechanism; chat applies it before every LLM call in M4 (CHAT-19).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .identity import IdentityKind

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
