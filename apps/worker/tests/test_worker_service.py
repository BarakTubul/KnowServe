"""M0-04 Worker service tests: M0-AC04, M0-AC05, M0-AC10, M0-AC14 (worker side).

Covers ING-10, ING-12..15, ING-21, SEC-14, LIFE-09, MON-03. Signatures are produced locally with
PyJWT and the Google verifier is a fake: this does not prove live QStash or live Google OIDC.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core import request_context
from knowserve_core.jobs import enqueue_job
from knowserve_core.logging import configure_logging
from knowserve_core.qstash import FakePublisher
from knowserve_core.settings import Settings
from knowserve_worker.app import JobContext, create_app

pytestmark = [pytest.mark.m0, pytest.mark.worker]
integration = pytest.mark.integration

CURRENT = "local-only-qstash-current-key-not-a-secret"
NEXT = "local-only-qstash-next-key-not-a-secret"
LOCAL_TOKEN = "local-only-dispatcher-token-not-a-secret"
PUBLIC_URL = "https://worker.test"
RUN_URL = PUBLIC_URL + "/internal/jobs/run"
Factory = async_sessionmaker[AsyncSession]


def make_settings(database_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": database_url,
        "env": "local",
        "qstash_current_signing_key": CURRENT,
        "qstash_next_signing_key": NEXT,
        "dispatcher_local_token": LOCAL_TOKEN,
        "worker_public_url": PUBLIC_URL,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def sign(payload: bytes, /, key: str = CURRENT, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "Upstash",
        "sub": RUN_URL,
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "body": base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("="),
    }
    claims.update(overrides)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm="HS256")


def envelope(job_id: uuid.UUID | str, version: int = 1) -> bytes:
    return json.dumps({"schema_version": version, "job_id": str(job_id)}).encode()


class Counting:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.calls: list[JobContext] = []
        self.delay = delay
        self.fail = fail

    async def __call__(self, ctx: JobContext) -> None:
        self.calls.append(ctx)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("handler exploded")


class Harness:
    def __init__(self, engine: AsyncEngine, factory: Factory, url: str) -> None:
        self.engine, self.factory, self.url = engine, factory, url
        self.handler = Counting()
        self.publisher = FakePublisher()

    def app(self, **settings_overrides: Any) -> Any:
        return create_app(
            settings=make_settings(self.url, **settings_overrides),
            engine=self.engine,
            publisher=self.publisher,
            handlers={"noop": self.handler},
        )

    def client(self, app: Any = None) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app or self.app(), raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL, timeout=30)

    async def enqueue(self, correlation_id: str | None = None) -> uuid.UUID:
        async with self.factory() as s, s.begin():
            return (await enqueue_job(s, "noop", correlation_id=correlation_id)).id

    async def job(self, job_id: uuid.UUID) -> Any:
        async with self.factory() as s:
            return (
                await s.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id})
            ).one()

    async def sql(self, statement: str) -> None:
        async with self.factory() as s, s.begin():
            await s.execute(text(statement))

    async def deliver(
        self, client: httpx.AsyncClient, job_id: uuid.UUID | str, **kw: Any
    ) -> httpx.Response:
        body = envelope(job_id)
        return await client.post(
            "/internal/jobs/run",
            content=body,
            headers={"Upstash-Signature": sign(body, **kw), "Content-Type": "application/json"},
        )


@pytest_asyncio.fixture
async def h(
    engine: AsyncEngine, session_factory: Factory, database_url: str
) -> AsyncIterator[Harness]:
    yield Harness(engine, session_factory, database_url)


# --------------------------------------------------------------------------- signature (SEC-14)


@integration
async def test_sec14_valid_signature_current_key_runs_job(h: Harness) -> None:
    job_id = await h.enqueue()
    async with h.client() as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 200 and response.json() == {"result": "done"}
    assert len(h.handler.calls) == 1
    assert (await h.job(job_id)).status == "done"


@integration
async def test_sec14_valid_signature_next_key_runs_job(h: Harness) -> None:
    job_id = await h.enqueue()
    async with h.client() as c:
        response = await h.deliver(c, job_id, key=NEXT)
    assert response.status_code == 200 and len(h.handler.calls) == 1


@integration
@pytest.mark.parametrize(
    "case",
    ["missing", "bad_key", "expired", "body_mismatch", "wrong_sub", "wrong_iss", "garbage"],
)
async def test_sec14_invalid_signature_is_401_with_no_work(h: Harness, case: str) -> None:
    job_id = await h.enqueue()
    body = envelope(job_id)
    headers: dict[str, str] = {}
    if case == "bad_key":
        headers["Upstash-Signature"] = sign(body, key="some-other-key")
    elif case == "expired":
        headers["Upstash-Signature"] = sign(body, exp=int(time.time()) - 600)
    elif case == "body_mismatch":
        headers["Upstash-Signature"] = sign(envelope(uuid.uuid4()))
    elif case == "wrong_sub":
        headers["Upstash-Signature"] = sign(body, sub="https://evil.test/internal/jobs/run")
    elif case == "wrong_iss":
        headers["Upstash-Signature"] = sign(body, iss="Nobody")
    elif case == "garbage":
        headers["Upstash-Signature"] = "not.a.jwt"
    before = await h.job(job_id)
    async with h.client() as c:
        response = await c.post("/internal/jobs/run", content=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert h.handler.calls == []
    after = await h.job(job_id)
    assert (after.status, after.attempts, after.updated_at) == (
        before.status,
        before.attempts,
        before.updated_at,
    )


@integration
async def test_sec14_unsigned_request_is_401_even_for_malformed_body(h: Harness) -> None:
    async with h.client() as c:
        response = await c.post("/internal/jobs/run", content=b"not json")
    assert response.status_code == 401


@integration
async def test_sec14_no_signing_keys_configured_fails_closed(h: Harness) -> None:
    job_id = await h.enqueue()
    app = h.app(qstash_current_signing_key=None, qstash_next_signing_key=None)
    async with h.client(app) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 401 and h.handler.calls == []


# --------------------------------------------------------------------------- envelope / idempotency


@integration
async def test_ing10_unknown_schema_version_is_422(h: Harness) -> None:
    job_id = await h.enqueue()
    body = envelope(job_id, version=2)
    async with h.client() as c:
        response = await c.post(
            "/internal/jobs/run", content=body, headers={"Upstash-Signature": sign(body)}
        )
    assert response.status_code == 422 and h.handler.calls == []


@integration
async def test_ing10_malformed_job_id_is_422(h: Harness) -> None:
    body = json.dumps({"schema_version": 1, "job_id": "nope"}).encode()
    async with h.client() as c:
        response = await c.post(
            "/internal/jobs/run", content=body, headers={"Upstash-Signature": sign(body)}
        )
    assert response.status_code == 422


@integration
async def test_ing15_unknown_job_is_200_and_does_no_work(h: Harness) -> None:
    async with h.client() as c:
        response = await h.deliver(c, uuid.uuid4())
    assert response.status_code == 200 and response.json() == {"result": "unknown_job"}
    assert h.handler.calls == []


@integration
async def test_m0_ac04_redelivery_after_success_is_2xx_and_does_not_reexecute(h: Harness) -> None:
    job_id = await h.enqueue()
    async with h.client() as c:
        first = await h.deliver(c, job_id)
        second = await h.deliver(c, job_id)
        third = await h.deliver(c, job_id)
    assert first.json() == {"result": "done"}
    assert second.status_code == third.status_code == 200
    assert second.json() == {"result": "already_done"}
    assert len(h.handler.calls) == 1
    assert (await h.job(job_id)).attempts == 1


@integration
async def test_m0_ac04_concurrent_deliveries_execute_exactly_once(h: Harness) -> None:
    h.handler = Counting(delay=0.4)
    job_id = await h.enqueue()
    app = h.app()
    async with h.client(app) as c:
        responses = await asyncio.gather(*(h.deliver(c, job_id) for _ in range(8)))
    codes = [r.status_code for r in responses]
    assert set(codes) <= {200, 409}, codes
    assert len(h.handler.calls) == 1
    assert codes.count(200) >= 1
    job = await h.job(job_id)
    assert job.status == "done" and job.attempts == 1


@integration
async def test_m0_ac05_expired_lease_is_reclaimed_and_executed_once(h: Harness) -> None:
    """A worker crashed mid-job: status stays 'processing' with a lease that has expired."""
    job_id = await h.enqueue()
    await h.sql(
        f"UPDATE jobs SET status='processing', attempts=1, claimed_by='dead-worker', "
        f"lease_expires_at = now() - interval '1 minute' WHERE id = '{job_id}'"
    )
    async with h.client() as c:
        first = await h.deliver(c, job_id)
        second = await h.deliver(c, job_id)
    assert first.status_code == 200 and first.json() == {"result": "done"}
    assert second.json() == {"result": "already_done"}
    assert len(h.handler.calls) == 1
    job = await h.job(job_id)
    assert job.status == "done" and job.attempts == 2


@integration
async def test_m0_ac05_unexpired_lease_is_not_executed(h: Harness) -> None:
    job_id = await h.enqueue()
    await h.sql(
        f"UPDATE jobs SET status='processing', attempts=1, claimed_by='other-worker', "
        f"lease_expires_at = now() + interval '5 minutes' WHERE id = '{job_id}'"
    )
    async with h.client() as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_IN_PROGRESS"
    assert h.handler.calls == []
    job = await h.job(job_id)
    assert (job.status, job.claimed_by, job.attempts) == ("processing", "other-worker", 1)


@integration
async def test_ing21_handler_failure_returns_500_and_requeues_with_last_error(h: Harness) -> None:
    h.handler = Counting(fail=True)
    job_id = await h.enqueue()
    async with h.client() as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 500
    job = await h.job(job_id)
    assert job.status == "queued" and job.lease_expires_at is None and job.claimed_by is None
    assert "handler exploded" in job.last_error
    # The retried delivery runs again (and succeeds once the handler recovers).
    h.handler.fail = False
    async with h.client() as c:
        retry = await h.deliver(c, job_id)
    assert retry.status_code == 200
    job = await h.job(job_id)
    assert job.status == "done" and job.attempts == 2 and job.last_error is None


@integration
async def test_ing21_job_type_without_handler_is_failed_not_retried(h: Harness) -> None:
    job_id = await h.enqueue()
    await h.sql(f"UPDATE jobs SET job_type='mystery' WHERE id = '{job_id}'")
    async with h.client() as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 200 and response.json() == {"result": "failed"}
    assert (await h.job(job_id)).status == "failed"


# --------------------------------------------------------------------------- dispatcher auth


def fake_oidc(token: str, audience: str) -> dict[str, Any]:
    if token != "good-google-token" or audience != "https://worker.test":
        raise ValueError("invalid token")
    return {"email": "scheduler@proj.iam.gserviceaccount.com", "email_verified": True}


def prod_settings(url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "production",
        "dispatcher_local_token": None,
        "qstash_token": "prod-qstash-token",
        "dispatcher_oidc_audience": "https://worker.test",
        "dispatcher_oidc_service_account": "scheduler@proj.iam.gserviceaccount.com",
    }
    values.update(overrides)
    return make_settings(url, **values)


@integration
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"Bearer {LOCAL_TOKEN}", 200),
        (None, 401),
        ("Bearer wrong-token", 401),
        (f"Basic {LOCAL_TOKEN}", 401),
        ("Bearer", 401),
    ],
)
async def test_sec14_dispatcher_local_token(h: Harness, header: str | None, expected: int) -> None:
    job_id = await h.enqueue()
    headers = {"Authorization": header} if header else {}
    async with h.client() as c:
        response = await c.post("/internal/outbox/dispatch", headers=headers)
    assert response.status_code == expected
    if expected == 200:
        assert response.json() == {"published": 1, "failed": 0}
        assert h.publisher.published[0][0] == job_id
    else:
        assert h.publisher.published == []


@integration
async def test_sec14_dispatcher_local_token_unset_means_401(h: Harness) -> None:
    app = h.app(dispatcher_local_token=None)
    async with h.client(app) as c:
        response = await c.post(
            "/internal/outbox/dispatch", headers={"Authorization": f"Bearer {LOCAL_TOKEN}"}
        )
    assert response.status_code == 401


def _prod_app(h: Harness, **overrides: Any) -> Any:
    return create_app(
        settings=prod_settings(h.url, **overrides),
        engine=h.engine,
        publisher=h.publisher,
        handlers={"noop": h.handler},
        oidc_verifier=fake_oidc,
    )


@integration
@pytest.mark.parametrize(
    ("header", "overrides", "expected"),
    [
        ("Bearer good-google-token", {}, 200),
        ("Bearer bad-google-token", {}, 401),
        ("Bearer good-google-token", {"dispatcher_oidc_audience": "https://other"}, 401),
        (
            "Bearer good-google-token",
            {"dispatcher_oidc_service_account": "attacker@proj.iam.gserviceaccount.com"},
            401,
        ),
        (f"Bearer {LOCAL_TOKEN}", {}, 401),
        (None, {}, 401),
    ],
)
async def test_sec14_dispatcher_production_oidc_with_fake_verifier(
    h: Harness, header: str | None, overrides: dict[str, Any], expected: int
) -> None:
    await h.enqueue()
    app = _prod_app(h, **overrides)
    headers = {"Authorization": header} if header else {}
    async with h.client(app) as c:
        response = await c.post("/internal/outbox/dispatch", headers=headers)
    assert response.status_code == expected


@integration
async def test_sec14_dispatcher_production_rejects_unverified_email(h: Harness) -> None:
    def unverified(token: str, audience: str) -> dict[str, Any]:
        return {"email": "scheduler@proj.iam.gserviceaccount.com", "email_verified": False}

    app = create_app(
        settings=prod_settings(h.url), engine=h.engine, publisher=h.publisher,
        oidc_verifier=unverified,
    )  # fmt: skip
    async with h.client(app) as c:
        response = await c.post(
            "/internal/outbox/dispatch", headers={"Authorization": "Bearer good-google-token"}
        )
    assert response.status_code == 401


@integration
async def test_m0_ac10_dispatch_endpoint_recovers_unpublished_job_once(h: Harness) -> None:
    job_id = await h.enqueue()
    auth = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
    async with h.client() as c:
        first = await c.post("/internal/outbox/dispatch", headers=auth)
        second = await c.post("/internal/outbox/dispatch", headers=auth)
    assert first.json() == {"published": 1, "failed": 0}
    assert second.json() == {"published": 0, "failed": 0}
    assert [j for j, _ in h.publisher.published] == [job_id]


@integration
async def test_m0_ac10_dispatch_reports_failures(h: Harness) -> None:
    await h.enqueue()
    h.publisher.fail = True
    async with h.client() as c:
        response = await c.post(
            "/internal/outbox/dispatch", headers={"Authorization": f"Bearer {LOCAL_TOKEN}"}
        )
    assert response.json() == {"published": 0, "failed": 1}


# --------------------------------------------------------------------------- logging / health


def _log_lines(buffer: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]


@integration
async def test_mon03_correlation_id_from_enqueue_appears_in_worker_logs(h: Harness) -> None:
    request_context.clear()
    request_context.set_request_id("req_api_origin_01")
    try:
        job_id = await h.enqueue()
    finally:
        request_context.clear()
    app = h.app()
    buffer = io.StringIO()
    configure_logging("worker", "INFO", stream=buffer)
    async with h.client(app) as c:
        response = await h.deliver(c, job_id)
    assert response.status_code == 200
    lines = _log_lines(buffer)
    job_lines = [x for x in lines if x.get("job_id") == str(job_id)]
    assert job_lines, lines
    assert {x["correlation_id"] for x in job_lines} == {"req_api_origin_01"}
    assert all(x["service"] == "worker" for x in lines)
    assert all(x["request_id"] != "req_api_origin_01" for x in job_lines)


@integration
async def test_sec14_secrets_never_appear_in_logs(h: Harness) -> None:
    job_id = await h.enqueue()
    app = h.app()
    buffer = io.StringIO()
    configure_logging("worker", "DEBUG", stream=buffer)
    body = envelope(job_id)
    good = sign(body)
    bad = sign(body, key="attacker-key-value")
    async with h.client(app) as c:
        await c.post("/internal/jobs/run", content=body, headers={"Upstash-Signature": bad})
        await c.post(
            "/internal/outbox/dispatch", headers={"Authorization": "Bearer attacker-bearer"}
        )
        await c.post(
            "/internal/outbox/dispatch", headers={"Authorization": f"Bearer {LOCAL_TOKEN}"}
        )
        await c.post("/internal/jobs/run", content=body, headers={"Upstash-Signature": good})
    output = buffer.getvalue()
    for secret in (CURRENT, NEXT, LOCAL_TOKEN, good, bad, "attacker-key-value", "attacker-bearer"):
        assert secret not in output


async def test_health_live_needs_no_database(database_url: str) -> None:
    app = create_app(
        settings=make_settings("postgresql+asyncpg://x:y@127.0.0.1:1/none"),
        publisher=FakePublisher(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get("/health/live")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


@integration
async def test_health_ready_ok_with_database(h: Harness) -> None:
    async with h.client() as c:
        response = await c.get("/health/ready")
    assert response.status_code == 200 and response.json() == {"status": "ready"}


async def test_health_ready_503_envelope_with_dead_database() -> None:
    app = create_app(
        settings=make_settings("postgresql+asyncpg://x:y@127.0.0.1:1/none"),
        publisher=FakePublisher(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


# --------------------------------------------------------------------------- startup guards


@pytest.mark.parametrize(
    "missing",
    [
        "worker_public_url",
        "qstash_token",
        "qstash_current_signing_key",
        "qstash_next_signing_key",
        "dispatcher_oidc_audience",
        "dispatcher_oidc_service_account",
    ],
)
def test_sec14_production_refuses_to_start_when_setting_missing(missing: str) -> None:
    settings = prod_settings("postgresql+asyncpg://x:y@127.0.0.1:1/none", **{missing: None})
    with pytest.raises(RuntimeError, match="refuses to start"):
        create_app(settings=settings, publisher=FakePublisher())


async def test_sec14_production_starts_with_all_settings() -> None:
    app = create_app(
        settings=prod_settings("postgresql+asyncpg://x:y@127.0.0.1:1/none"),
        publisher=FakePublisher(),
    )
    await app.state.engine.dispose()


def test_sec14_production_rejects_local_dispatcher_token_in_settings() -> None:
    with pytest.raises(ValueError, match="DISPATCHER_LOCAL_TOKEN"):
        prod_settings("postgresql+asyncpg://x:y@127.0.0.1:1/none", dispatcher_local_token="x")


@pytest.mark.parametrize("field", ["worker_public_url", "qstash_url"])
def test_sec14_production_requires_https_urls(field: str) -> None:
    settings = prod_settings(
        "postgresql+asyncpg://x:y@127.0.0.1:1/none", **{field: "http://insecure.test"}
    )
    with pytest.raises(RuntimeError, match="https required"):
        create_app(settings=settings, publisher=FakePublisher())


@integration
async def test_sec14_oversized_body_is_rejected_before_any_work(h: Harness) -> None:
    job_id = await h.enqueue()
    big = b"x" * 10_000
    async with h.client() as client:
        response = await client.post(
            "/internal/jobs/run", content=big, headers={"Upstash-Signature": sign(big)}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert h.handler.calls == []
    assert (await h.job(job_id)).status == "queued"
