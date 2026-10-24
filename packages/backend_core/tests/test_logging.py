"""MON-03 / MON-05 / ARCH-09: JSON logs carry ids and never contain secrets."""

import io
import json
import logging

import pytest

from knowserve_core import request_context
from knowserve_core.logging import REDACTED, configure_logging, redact


def _log_once(**extra: object) -> dict:
    stream = io.StringIO()
    configure_logging("test-service", "INFO", stream=stream)
    logging.getLogger("knowserve.test").info("hello", extra=extra)
    return json.loads(stream.getvalue().strip().splitlines()[-1])


@pytest.mark.m0
def test_mon_03_log_line_is_json_with_service_and_correlation_id() -> None:
    request_context.clear()
    request_context.set_request_id("req_abcdef123456")
    request_context.set_correlation_id("corr_0123456789")
    line = _log_once(job_id="job-1")
    assert line["service"] == "test-service"
    assert line["request_id"] == "req_abcdef123456"
    assert line["correlation_id"] == "corr_0123456789"
    assert line["job_id"] == "job-1"
    request_context.clear()


@pytest.mark.m0
def test_mon_05_sensitive_fields_are_redacted() -> None:
    line = _log_once(
        password="hunter2",
        cookie="session=abc",
        authorization="Bearer abc.def",
        otp_code="123456",
        nested={"api_key": "k", "ok": "fine"},
    )
    assert line["password"] == REDACTED
    assert line["cookie"] == REDACTED
    assert line["authorization"] == REDACTED
    assert line["otp_code"] == REDACTED
    assert line["nested"] == {"api_key": REDACTED, "ok": "fine"}


@pytest.mark.m0
def test_mon_05_bearer_tokens_inside_messages_are_masked() -> None:
    assert "abc.def" not in redact("sent header Bearer abc.def to host")
