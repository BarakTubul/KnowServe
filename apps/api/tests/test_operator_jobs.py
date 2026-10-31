"""M0-AC10, M0-AC16, M0-AC17: the restricted operator job surface and immediate publish.

Requirement ids: ING-12/13/16 (immediate publish, manual retry), ADM-16 (core), SEC-14/SEC-15
(no unauthenticated internal routes), SEC-13 (proxy guard stays on). The Google verifier is a
fake: this does not prove live Google ID tokens or live QStash.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.app import create_app
from knowserve_api.operator import MAX_OPEN_JOBS
from knowserve_core.qstash import FakePublisher
from knowserve_core.settings import Settings

pytestmark = [pytest.mark.m0, pytest.mark.api, pytest.mark.integration]

AUDIENCE = "https://api.test"
OPERATOR = "operator@example.test"
PROXY_SECRET = "local-only-proxy-secret-not-a-secret"
GOOD = {"Authorization": "Bearer good-token"}
Factory = async_sessionmaker[AsyncSession]


def fake_verifier(token: str, audience: str) -> dict[str, Any]:
    if audience != AUDIENCE:
        raise ValueError("wrong audience")
    claims: dict[str, dict[str, Any]] = {
        "good-token": {"email": OPERATOR, "email_verified": True},
        "upper-token": {"email": OPERATOR.upper(), "email_verified": True},
        "stranger-token": {"email": "stranger@example.test", "email_verified": True},
        "unverified-token": {"email": OPERATOR, "email_verified": False},
        "no-email-token": {"email_verified": True},
    }
    if token not in claims:
        raise ValueError("bad token")
    return claims[token]


def make_settings(url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": url,
        "env": "ci",
        "enable_spike_job_ops": True,
        "spike_operator_emails": [OPERATOR],
        "spike_oidc_audience": AUDIENCE,
        "enable_spike_failure_hooks": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class Harness:
    def __init__(self, engine: AsyncEngine, factory: Factory, url: str) -> None:
        self.engine, self.factory, self.url = engine, factory, url
        self.publisher = FakePublisher()

    def app(self, publisher: Any = None, **overrides: Any) -> FastAPI:
        return create_app(
            make_settings(self.url, **overrides),
            self.engine,
            publisher=publisher or self.publisher,
            oidc_verifier=fake_verifier,
        )

    def client(self, app: FastAPI) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        return httpx.AsyncClient(transport=transport, base_url="https://test")

    async def sql(self, statement: str, **params: Any) -> None:
        async with self.factory() as s, s.begin():
            await s.execute(text(statement), params)


@pytest_asyncio.fixture
async def h(
    engine: AsyncEngine, session_factory: Factory, database_url: str
) -> AsyncIterator[Harness]:
    yield Harness(engine, session_factory, database_url)


# ------------------------------------------------------------------ mounting and authentication


async def test_m0_ac17_routes_do_not_exist_unless_job_ops_is_enabled(h: Harness) -> None:
    app = h.app(enable_spike_job_ops=False, enable_spike_failure_hooks=False)
    async with h.client(app) as c:
        responses = [
            await c.get("/internal/spike/jobs", headers=GOOD),
            await c.post("/internal/spike/jobs", headers=GOOD, json={}),
            await c.post(f"/internal/spike/jobs/{uuid.uuid4()}/retry", headers=GOOD),
        ]
    assert [r.status_code for r in responses] == [404, 404, 404]


async def test_m0_ac17_job_ops_cannot_be_enabled_without_operators_and_audience() -> None:
    with pytest.raises(ValueError, match="KS_SPIKE_OPERATOR_EMAILS"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,  # pyright: ignore[reportCallIssue]
            database_url="postgresql://u:p@localhost/db",
            enable_spike_job_ops=True,
        )
    with pytest.raises(ValueError, match="KS_ENABLE_SPIKE_JOB_OPS"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,  # pyright: ignore[reportCallIssue]
            database_url="postgresql://u:p@localhost/db",
            enable_spike_failure_hooks=True,
        )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Basic good-token"},
        {"Authorization": "Bearer bogus"},
        {"Authorization": "Bearer stranger-token"},
        {"Authorization": "Bearer unverified-token"},
        {"Authorization": "Bearer no-email-token"},
    ],
)
async def test_m0_ac17_every_route_needs_a_verified_allow_listed_operator(
    h: Harness, headers: dict[str, str]
) -> None:
    job_id = uuid.uuid4()
    async with h.client(h.app()) as c:
        responses = [
            await c.get("/internal/spike/jobs", headers=headers),
            await c.get(f"/internal/spike/jobs/{job_id}", headers=headers),
            await c.post("/internal/spike/jobs", headers=headers, json={}),
            await c.post(f"/internal/spike/jobs/{job_id}/retry", headers=headers),
        ]
    for response in responses:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"
        assert "operator" not in response.text.lower() and "token" not in response.text.lower()
    assert h.publisher.published == []


async def test_m0_ac17_operator_email_match_ignores_case(h: Harness) -> None:
    async with h.client(h.app()) as c:
        response = await c.get(
            "/internal/spike/jobs", headers={"Authorization": "Bearer upper-token"}
        )
    assert response.status_code == 200


async def test_m0_ac17_proxy_guard_still_applies_to_operator_routes(h: Harness) -> None:
    app = h.app(proxy_shared_secret=PROXY_SECRET)
    async with h.client(app) as c:
        direct = await c.get("/internal/spike/jobs", headers=GOOD)
        wrong = await c.get("/internal/spike/jobs", headers={**GOOD, "X-KS-Proxy-Secret": "nope"})
        both = await c.get(
            "/internal/spike/jobs", headers={**GOOD, "X-KS-Proxy-Secret": PROXY_SECRET}
        )
        secret_only = await c.get(
            "/internal/spike/jobs", headers={"X-KS-Proxy-Secret": PROXY_SECRET}
        )
    assert direct.status_code == 403 and wrong.status_code == 403
    assert both.status_code == 200
    assert secret_only.status_code == 401  # the proxy secret alone is not user authentication


async def test_m0_ac17_routes_are_hidden_from_the_public_openapi(h: Harness) -> None:
    paths = h.app().openapi()["paths"]
    assert not [p for p in paths if "spike/jobs" in p or p.startswith("/internal")]
    async with h.client(h.app()) as c:
        public = await c.get("/v1/spike/jobs", headers=GOOD)
    assert public.status_code == 404  # nothing under /v1 (the only path Pages forwards)


# ------------------------------------------------------------ immediate publish and statuses


async def test_ing13_create_publishes_inside_the_request(h: Harness) -> None:
    async with h.client(h.app()) as c:
        response = await c.post("/internal/spike/jobs", headers=GOOD, json={"job_type": "noop"})
    body = response.json()
    assert response.status_code == 201
    assert body["delivery_state"] == "queued" and body["retry_action"] is None
    assert [p[0] for p in h.publisher.published] == [uuid.UUID(body["id"])]  # before the response


async def test_ing13_publish_failure_keeps_the_job_and_reports_publish_failed(h: Harness) -> None:
    async with h.client(h.app(publisher=FakePublisher(fail=True))) as c:
        created = await c.post("/internal/spike/jobs", headers=GOOD, json={})
        listed = await c.get("/internal/spike/jobs", headers=GOOD)
    assert created.status_code == 201
    assert created.json()["delivery_state"] == "publish_failed"
    assert created.json()["retry_action"] == "republish"
    assert created.json()["publish_error"]
    assert [j["id"] for j in listed.json()] == [created.json()["id"]]


async def test_ing13_hanging_publish_is_bounded_and_the_job_stays_retryable(h: Harness) -> None:
    started = time.monotonic()
    async with h.client(h.app(publisher=FakePublisher(delay=30), publish_timeout_seconds=0.2)) as c:
        response = await c.post("/internal/spike/jobs", headers=GOOD, json={})
    assert time.monotonic() - started < 5
    assert response.status_code == 201
    assert response.json()["delivery_state"] == "publish_failed"
    assert "unconfirmed" in response.json()["publish_error"]


async def test_m0_ac10_crash_after_commit_job_is_listed_and_retried_once(h: Harness) -> None:
    async with h.client(h.app()) as c:
        created = await c.post("/internal/spike/jobs", headers=GOOD, json={"skip_publish": True})
        job_id = created.json()["id"]
        assert created.json()["delivery_state"] == "publish_pending"
        assert (await c.get("/internal/spike/jobs", headers=GOOD)).json() == []  # young: not stuck
        await h.sql(
            "UPDATE outbox SET created_at = now() - interval '10 minutes' WHERE job_id = :id",
            id=uuid.UUID(job_id),
        )
        attention = (await c.get("/internal/spike/jobs", headers=GOOD)).json()
        assert [(j["id"], j["delivery_state"]) for j in attention] == [
            (job_id, "unpublished_stuck")
        ]
        retried = await c.post(f"/internal/spike/jobs/{job_id}/retry", headers=GOOD)
        again = await c.post(f"/internal/spike/jobs/{job_id}/retry", headers=GOOD)
        one = await c.get(f"/internal/spike/jobs/{job_id}", headers=GOOD)
    assert retried.status_code == 200
    assert retried.json()["action"] == "republish" and retried.json()["published"] is True
    assert again.status_code == 409 and again.json()["error"]["code"] == "JOB_NOT_RETRYABLE"
    assert one.json()["delivery_state"] == "queued"
    assert len(h.publisher.published) == 1


async def test_m0_ac16_failed_job_is_listed_and_requeued_by_retry(h: Harness) -> None:
    async with h.client(h.app()) as c:
        job_id = (await c.post("/internal/spike/jobs", headers=GOOD, json={})).json()["id"]
        await h.sql(
            "UPDATE jobs SET status = 'failed', attempts = 4, last_error = 'boom' WHERE id = :id",
            id=uuid.UUID(job_id),
        )
        listed = (await c.get("/internal/spike/jobs", headers=GOOD)).json()
        retried = await c.post(f"/internal/spike/jobs/{job_id}/retry", headers=GOOD)
    assert [(j["id"], j["delivery_state"], j["retry_action"]) for j in listed] == [
        (job_id, "failed", "requeue")
    ]
    assert retried.status_code == 200 and retried.json()["action"] == "requeue"
    assert retried.json()["job"]["attempts"] == 0 and len(h.publisher.published) == 2


async def test_m0_ac16_retry_is_rejected_for_done_and_actively_processing_jobs(h: Harness) -> None:
    async with h.client(h.app()) as c:
        done = (await c.post("/internal/spike/jobs", headers=GOOD, json={})).json()["id"]
        busy = (await c.post("/internal/spike/jobs", headers=GOOD, json={})).json()["id"]
        await h.sql("UPDATE jobs SET status = 'done' WHERE id = :id", id=uuid.UUID(done))
        await h.sql(
            "UPDATE jobs SET status = 'processing', lease_expires_at = now() + interval '1 minute'"
            " WHERE id = :id",
            id=uuid.UUID(busy),
        )
        results = [
            await c.post(f"/internal/spike/jobs/{done}/retry", headers=GOOD),
            await c.post(f"/internal/spike/jobs/{busy}/retry", headers=GOOD),
            await c.post(f"/internal/spike/jobs/{uuid.uuid4()}/retry", headers=GOOD),
        ]
    assert [r.status_code for r in results] == [409, 409, 404]
    assert len(h.publisher.published) == 2  # only the two creates


# ----------------------------------------------------------------- test hooks and the open cap


async def test_m0_ac17_failure_hooks_are_refused_unless_enabled(h: Harness) -> None:
    app = h.app(enable_spike_failure_hooks=False)
    async with h.client(app) as c:
        skip = await c.post("/internal/spike/jobs", headers=GOOD, json={"skip_publish": True})
        fail = await c.post("/internal/spike/jobs", headers=GOOD, json={"job_type": "always_fail"})
        ok = await c.post("/internal/spike/jobs", headers=GOOD, json={"job_type": "noop"})
        unknown = await c.post("/internal/spike/jobs", headers=GOOD, json={"job_type": "evil"})
    assert (skip.status_code, fail.status_code, ok.status_code) == (403, 403, 201)
    assert skip.json()["error"]["code"] == "FAILURE_HOOKS_DISABLED"
    assert unknown.status_code == 422
    assert len(h.publisher.published) == 1


async def test_m0_ac17_unfinished_test_jobs_are_capped(h: Harness) -> None:
    async with h.client(h.app()) as c:
        for _ in range(MAX_OPEN_JOBS):
            assert (await c.post("/internal/spike/jobs", headers=GOOD, json={})).status_code == 201
        over = await c.post("/internal/spike/jobs", headers=GOOD, json={})
    assert over.status_code == 429 and over.json()["error"]["code"] == "TOO_MANY_OPEN_JOBS"
    assert len(h.publisher.published) == MAX_OPEN_JOBS
