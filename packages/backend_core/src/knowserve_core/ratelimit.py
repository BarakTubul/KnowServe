"""Rate-limit interface (AUTH-15, ADR 0004). The PostgreSQL implementation is M1-02a."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter(Protocol):
    async def hit(
        self, session: AsyncSession, key: str, *, limit: int, window_seconds: int
    ) -> RateDecision:
        """Count one event for ``key`` in the current fixed window, atomically.

        The event is counted even when it is refused, so a client cannot probe the edge for free.
        """
        ...
