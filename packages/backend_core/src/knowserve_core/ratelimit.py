"""Rate-limit interface (AUTH-15, ADR 0004). The PostgreSQL implementation is M1-02a."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def client_bucket_key(address: str, pepper: bytes) -> str:
    """Limiter key for a client address: a keyed hash, never the address (SEC-18, OPEN-28 Q9).

    HMAC-SHA256 with a secret pepper, so a counter row cannot be reversed to an address by anyone
    who reads the database without the pepper. The key is stable while the pepper is, which the
    fixed-window limit needs.
    """
    digest = hmac.new(pepper, address.encode(), hashlib.sha256).hexdigest()
    return f"demo:client:{digest}"


class RateLimiter(Protocol):
    async def hit(
        self, session: AsyncSession, key: str, *, limit: int, window_seconds: int
    ) -> RateDecision:
        """Count one event for ``key`` in the current fixed window, atomically.

        The event is counted even when it is refused, so a client cannot probe the edge for free.
        """
        ...
