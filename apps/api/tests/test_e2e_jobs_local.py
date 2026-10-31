"""M0-AC10, M0-AC16: local end-to-end job flows, operator routes -> simulated QStash -> Worker.

LOCAL SIMULATION. ``QStashSim`` signs the real envelope with the Worker's signing key and
re-delivers on non-2xx the way QStash is documented to (default 3 retries, i.e. 4 deliveries in
total: UNVERIFIED against a live QStash). It proves our code's behaviour under that assumption; it
does not prove live QStash delivery, retry counts or signatures.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
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

from knowserve_api.app import create_app as create_api
from knowserve_core.settings import Settings
from knowserve_worker.app import (
    JobContext,
    always_fail_handler,
    noop_handler,
)
from knowserve_worker.app import create_app as create_worker

pytestmark = [pytest.mark.m0, pytest.mark.api, pytest.mark.worker, pytest.mark.integration]

KEY = "local-only-qstash-current-key-not-a-secret"
WORKER_URL = "https://worker.test"
RUN_URL = WORKER_URL + "/internal/jobs/run"
AUDIENCE = "https://api.test"
OPERATOR = "operator@example.test"
GOOD = {"Authorization": "Bearer good"}
Factory = async_sessionmaker[AsyncSession]


def verifier(token: str, audience: str) -> dict[str, Any]:
    if token != "good" or audience != AUDIENCE:
        raise ValueError("rejected")
    return {"email": OPERATOR, "email_verified": True}


class QStashSim:
    """Publisher that delivers to the Worker app and re-delivers failures like QStash would."""

    def __init__(self, worker: httpx.AsyncClient, retries: int = 3) -> None:
        self.worker, self.retries = worker, retries
        self.deliveries: list[int] = []
        self.pending: list[asyncio.Task[None]] = []

    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        body = json.dumps({"schema_version": 1, "job_id": str(job_id)}).encode()
        for _ in range(1 + self.retries):
            status = await self.deliver(body)
            self.deliveries.append(status)
            if 200 <= status < 300:
                return

    async def deliver(self, body: bytes) -> int:
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": "Upstash",
                "sub": RUN_URL,
                "nbf": now,
                "exp": now + 300,
                "body": base64.urlsafe_b64encode(hashlib.sha256(body).digest())
                .decode()
                .rstrip("="),
            },
            KEY,
            algorithm="HS256",
        )
        response = await self.worker.post(
            "/internal/jobs/run", content=body, headers={"Upstash-Signature": token}
        )
        return response.status_code


class Stack:
    def __init__(self, engine: AsyncEngine, factory: Factory, url: str) -> None:
        self.engine, self.factory, self.url = engine, factory, url
        self.calls: list[JobContext] = []
        self.flaky_failures = 0
        self.worker_app = create_worker(
            Settings(  # type: ignore[call-arg]
                _env_file=None,  # pyright: ignore[reportCallIssue]
                database_url=url,
                env="ci",
                qstash_current_signing_key=KEY,
                qstash_next_signing_key="local-only-qstash-next-key-not-a-secret",
                worker_public_url=WORKER_URL,
                enable_spike_failure_hooks=True,
                enable_spike_job_ops=True,
                spike_operator_emails=[OPERATOR],
                spike_oidc_audience=AUDIENCE,
            ),
            engine=engine,
            handlers={"noop": self.noop, "always_fail": self.always_fail},
        )
        self.worker = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.worker_app, raise_app_exceptions=False),
            base_url=WORKER_URL,
        )
        self.sim = QStashSim(self.worker)

    async def noop(self, ctx: JobContext) -> None:
        self.calls.append(ctx)
        if self.flaky_failures > 0:
            self.flaky_failures -= 1
            raise RuntimeError("transient")
        await noop_handler(ctx)

    async def always_fail(self, ctx: JobContext) -> None:
        self.calls.append(ctx)
        await always_fail_handler(ctx)

    def api(self) -> httpx.AsyncClient:
        app = create_api(
            Settings(  # type: ignore[call-arg]
                _env_file=None,  # pyright: ignore[reportCallIssue]
                database_url=self.url,
                env="ci",
                enable_spike_job_ops=True,
                enable_spike_failure_hooks=True,
                spike_operator_emails=[OPERATOR],
                spike_oidc_audience=AUDIENCE,
            ),
            self.engine,
            publisher=self.sim,  # type: ignore[arg-type]
            oidc_verifier=verifier,
        )
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="https://api.test",
        )

    async def sql(self, statement: str, **params: Any) -> None:
        async with self.factory() as s, s.begin():
            for part in statement.split(";"):
                if part.strip():
                    await s.execute(text(part), params)

    async def state(self, api: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
        return (await api.get(f"/internal/spike/jobs/{job_id}", headers=GOOD)).json()


@pytest_asyncio.fixture
async def stack(
    engine: AsyncEngine, session_factory: Factory, database_url: str
) -> AsyncIterator[Stack]:
    yield Stack(engine, session_factory, database_url)


async def test_m0_ac10_happy_path_publishes_inside_the_request_and_completes(stack: Stack) -> None:
    async with stack.api() as api:
        created = (await api.post("/internal/spike/jobs", headers=GOOD, json={})).json()
        final = await stack.state(api, created["id"])
    assert stack.sim.deliveries == [200] and len(stack.calls) == 1
    assert final["delivery_state"] == "done"


async def test_m0_ac16_transient_processing_failure_is_retried_by_the_queue(stack: Stack) -> None:
    stack.flaky_failures = 2
    async with stack.api() as api:
        created = (await api.post("/internal/spike/jobs", headers=GOOD, json={})).json()
        final = await stack.state(api, created["id"])
    assert stack.sim.deliveries == [500, 500, 200]  # never a 2xx while a retry was still needed
    assert final["delivery_state"] == "done" and len(stack.calls) == 3


async def test_m0_ac16_exhausted_retries_end_failed_visible_and_retryable(stack: Stack) -> None:
    async with stack.api() as api:
        created = (
            await api.post("/internal/spike/jobs", headers=GOOD, json={"job_type": "always_fail"})
        ).json()
        job_id = created["id"]
        failed = await stack.state(api, job_id)
        listed = (await api.get("/internal/spike/jobs", headers=GOOD)).json()
        # QStash default (3 retries) = 4 deliveries = KS_JOB_MAX_ATTEMPTS: both stop together.
        assert stack.sim.deliveries == [500, 500, 500, 500] and len(stack.calls) == 4
        assert failed["delivery_state"] == "failed" and failed["attempts"] == 4
        assert [(j["id"], j["retry_action"]) for j in listed] == [(job_id, "requeue")]
        # A late duplicate delivery of the failed job does no work and is acknowledged (terminal).
        late = await stack.sim.deliver(json.dumps({"schema_version": 1, "job_id": job_id}).encode())
        assert late == 200 and len(stack.calls) == 4
        retried = await api.post(f"/internal/spike/jobs/{job_id}/retry", headers=GOOD)
        again = await stack.state(api, job_id)
    assert retried.status_code == 200 and retried.json()["action"] == "requeue"
    assert len(stack.calls) == 8 and again["delivery_state"] == "failed"  # a fresh budget of 4


async def test_m0_ac16_a_shorter_queue_retry_count_leaves_the_job_stuck_not_lost(
    stack: Stack,
) -> None:
    """If QStash retried fewer than 4 times, the job is `queued_stuck` and still recoverable."""
    stack.sim.retries = 1  # 2 deliveries only
    async with stack.api() as api:
        created = (
            await api.post("/internal/spike/jobs", headers=GOOD, json={"job_type": "always_fail"})
        ).json()
        job_id = created["id"]
        mid = await stack.state(api, job_id)
        assert mid["delivery_state"] == "queued" and mid["attempts"] == 2
        await stack.sql(
            "UPDATE jobs SET updated_at = now() - interval '1 hour' WHERE id = :id;"
            "UPDATE outbox SET published_at = now() - interval '1 hour' WHERE job_id = :id",
            id=uuid.UUID(job_id),
        )
        stuck = await stack.state(api, job_id)
        retried = await api.post(f"/internal/spike/jobs/{job_id}/retry", headers=GOOD)
    assert stuck["delivery_state"] == "queued_stuck" and stuck["retry_action"] == "requeue"
    assert retried.status_code == 200 and retried.json()["action"] == "requeue"


async def test_m0_ac10_api_crash_after_commit_then_manual_retry_completes(stack: Stack) -> None:
    async with stack.api() as api:
        created = (
            await api.post("/internal/spike/jobs", headers=GOOD, json={"skip_publish": True})
        ).json()
        job_id = created["id"]
        assert stack.sim.deliveries == [] and created["delivery_state"] == "publish_pending"
        await stack.sql(
            "UPDATE outbox SET created_at = now() - interval '10 minutes' WHERE job_id = :id",
            id=uuid.UUID(job_id),
        )
        retried = await api.post(f"/internal/spike/jobs/{job_id}/retry", headers=GOOD)
        final = await stack.state(api, job_id)
    assert retried.json()["action"] == "republish" and final["delivery_state"] == "done"
    assert stack.sim.deliveries == [200] and len(stack.calls) == 1


async def test_ing15_duplicate_and_concurrent_deliveries_run_the_job_once(stack: Stack) -> None:
    async with stack.api() as api:
        created = (await api.post("/internal/spike/jobs", headers=GOOD, json={})).json()
        body = json.dumps({"schema_version": 1, "job_id": created["id"]}).encode()
        duplicates = await asyncio.gather(*[stack.sim.deliver(body) for _ in range(5)])
    assert all(code == 200 for code in duplicates) and len(stack.calls) == 1
