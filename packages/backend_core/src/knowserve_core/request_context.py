"""Request and correlation ids carried through logs, the outbox and the Worker (MON-03)."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_VALID_ID = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def accept_or_new_request_id(candidate: str | None) -> str:
    """Use an inbound id only if it is well-formed; otherwise generate one."""
    if candidate and _VALID_ID.fullmatch(candidate):
        return candidate
    return new_request_id()


def set_request_id(value: str) -> None:
    _request_id.set(value)
    if _correlation_id.get() is None:
        _correlation_id.set(value)


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def get_correlation_id() -> str | None:
    return _correlation_id.get() or _request_id.get()


def clear() -> None:
    _request_id.set(None)
    _correlation_id.set(None)
