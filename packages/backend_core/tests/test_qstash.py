"""ING-13 / SEC-14: QStash publisher request shape and delivery-signature verification.

Locally signed tokens only; this does not prove behavior against a live QStash.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid

import httpx
import jwt
import pytest

from knowserve_core.qstash import HttpPublisher, PublishError, SignatureError, verify_signature

pytestmark = [pytest.mark.m0, pytest.mark.worker]

KEY = "unit-test-current-key"
NEXT = "unit-test-next-key"
URL = "https://worker.example/internal/jobs/run"


def sign(payload: bytes, /, key: str = KEY, **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "Upstash",
        "sub": URL,
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "body": base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("="),
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="HS256")


BODY = b'{"schema_version":1,"job_id":"x"}'


def check(token: str | None, body: bytes = BODY, url: str | None = URL) -> None:
    verify_signature(token=token, body=body, signing_keys=[KEY, NEXT], expected_url=url)


def test_ing13_valid_current_key() -> None:
    check(sign(BODY))


def test_ing13_valid_next_key() -> None:
    check(sign(BODY, key=NEXT))


@pytest.mark.parametrize(
    "token",
    [
        None,
        "",
        "not-a-jwt",
        sign(BODY, key="wrong-key"),
        sign(BODY, exp=int(time.time()) - 600),
        sign(BODY, nbf=int(time.time()) + 600),
        sign(BODY, iss="Someone"),
        sign(BODY, sub="https://evil.example/internal/jobs/run"),
        sign(BODY, body="AAAA"),
        sign(BODY, body=None),
        sign(BODY, exp=None),
    ],
)
def test_sec14_invalid_signatures_rejected(token: str | None) -> None:
    with pytest.raises(SignatureError):
        check(token)


def test_sec14_body_hash_mismatch_rejected() -> None:
    with pytest.raises(SignatureError):
        check(sign(BODY), body=b'{"schema_version":1,"job_id":"tampered"}')


def test_sec14_alg_none_rejected() -> None:
    def b64(data: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    now = int(time.time())
    token = (
        f"{b64({'alg': 'none', 'typ': 'JWT'})}."
        f"{b64({'iss': 'Upstash', 'nbf': now, 'exp': now + 300})}."
    )
    with pytest.raises(SignatureError):
        check(token)


def test_sec14_no_keys_configured_fails_closed() -> None:
    with pytest.raises(SignatureError):
        verify_signature(token=sign(BODY), body=BODY, signing_keys=[], expected_url=None)


def test_sec14_sub_not_checked_when_no_expected_url() -> None:
    check(sign(BODY, sub="anything"), url=None)


async def test_ing13_http_publisher_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "m1"})

    publisher = HttpPublisher(
        "https://qstash.test/",
        "tok-123",
        "https://worker.example/",
        transport=httpx.MockTransport(handler),
    )
    job_id = uuid.uuid4()
    await publisher.publish(job_id, "req_corr_00001")
    (request,) = seen
    assert request.method == "POST"
    assert (
        str(request.url)
        == "https://qstash.test/v2/publish/https://worker.example/internal/jobs/run"
    )
    assert request.headers["Authorization"] == "Bearer tok-123"
    assert request.headers["Upstash-Forward-X-Correlation-ID"] == "req_corr_00001"
    assert json.loads(request.content) == {"schema_version": 1, "job_id": str(job_id)}


async def test_ing13_http_publisher_failure_raises_publish_error_without_secret() -> None:
    publisher = HttpPublisher(
        "https://qstash.test",
        "tok-secret-xyz",
        "https://worker.example",
        transport=httpx.MockTransport(lambda r: httpx.Response(500)),
    )
    with pytest.raises(PublishError) as info:
        await publisher.publish(uuid.uuid4(), "req_corr_00001")
    assert "tok-secret-xyz" not in str(info.value)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    publisher = HttpPublisher(
        "https://qstash.test", "t", "https://w", transport=httpx.MockTransport(boom)
    )
    with pytest.raises(PublishError):
        await publisher.publish(uuid.uuid4(), "req_corr_00001")
