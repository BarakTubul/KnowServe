"""Structured JSON logging with redaction (ARCH-09, MON-03, MON-05). No print()."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from . import request_context

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"pass(word)?|secret|token|authorization|cookie|api[_-]?key|signing[_-]?key|otp|csrf|signature|session"
    r"|^ip$|_ip$|^ip_|client[_-]?ip|forwarded|remote[_-]?addr",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
# Firebase ID tokens are JWTs; mask one wherever it shows up inside a string value (MON-05).
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact(value: Any, key: str | None = None) -> Any:
    if key is not None and _SENSITIVE_KEY.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _JWT.sub(REDACTED, _BEARER.sub(r"\1" + REDACTED, value))
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": request_context.get_request_id(),
            "correlation_id": request_context.get_correlation_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in payload:
                payload[key] = redact(value, key)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def quiet_http_clients() -> None:
    """httpx logs every request URL at INFO. Object-store URLs carry the bucket host and the
    storage key, so client libraries log only warnings and errors (MON-05, DOC-04)."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(service: str, level: str = "INFO", stream: Any = None) -> None:
    """Replace root handlers with one JSON handler writing to stdout (Cloud Logging picks it up)."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    access = logging.getLogger("uvicorn.access")
    access.handlers[:] = []
    access.propagate = False
    quiet_http_clients()
