"""M2-PRIV: no client IP in the application database or logs (SEC-18, M2-AC21, OPEN-28 Q9).

Every M1 audit-writing path runs behind the proxy guard with a distinctive forwarded address and a
spoofed ``X-Forwarded-For``. Neither value may appear in ``audit_events``, in the limiter keys or in
any log record.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from http.cookiejar import DefaultCookiePolicy
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from knowserve_api.app import _ip_hash_pepper, create_app
from knowserve_core.clock import FakeClock
from knowserve_core.firebase_verifier import EMULATOR_ENV_VAR
from knowserve_core.logging import JsonFormatter, redact
from knowserve_core.ratelimit import client_bucket_key
from knowserve_core.ratelimit_pg import EXPIRY_GRACE_SECONDS, PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEFAULT_PROJECT_ID, mint_emulator_token

pytestmark = [pytest.mark.m2, pytest.mark.api, pytest.mark.integration]

ORIGIN = "http://localhost:5173"
COOKIE = "ks_session"
SECRET = "proxy-secret-for-tests-only"
PEPPER = "pepper-for-tests-0123456789"
ADDRESS = "203.0.113.77"
SPOOF = "198.51.100.99"
OTHER = "203.0.113.78"
PROXY = {"X-KS-Proxy-Secret": SECRET, "X-KS-Client-IP": ADDRESS, "X-Forwarded-For": SPOOF}


@pytest.fixture(autouse=True)
def _restore_emulator_env() -> Iterator[None]:
    saved = os.environ.get(EMULATOR_ENV_VAR)
    yield
    if saved is None:
        os.environ.pop(EMULATOR_ENV_VAR, None)
    else:
        os.environ[EMULATOR_ENV_VAR] = saved


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime.now(UTC))


def base_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_project_id": DEFAULT_PROJECT_ID,
        "firebase_auth_emulator_host": "localhost:9099",
        "api_allowed_origins": [ORIGIN],
        "proxy_shared_secret": SECRET,
        "ip_hash_pepper": PEPPER,
    }
    values.update(overrides)
    return values


def make_app(engine: AsyncEngine, clock: FakeClock, **overrides: Any) -> FastAPI:
    return create_app(
        Settings(_env_file=None, **base_values(**overrides)),  # type: ignore[call-arg]
        engine=engine,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
    )


def http(app: FastAPI) -> httpx.AsyncClient:
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")
    c.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))
    return c


def token(uid: str, provider: str, clock: FakeClock, **kw: Any) -> str:
    return mint_emulator_token(uid, provider=provider, issued_at=clock.now(), **kw)


def verified(uid: str, clock: FakeClock) -> str:
    return token(uid, "password", clock, email=f"{uid}@example.test", email_verified=True)


def post(c: httpx.AsyncClient, path: str, body: dict | None, extra: dict | None = None) -> Any:
    return c.post(path, json=body, headers={"Origin": ORIGIN, **PROXY, **(extra or {})})


def session_headers(response: httpx.Response) -> dict[str, str]:
    return {
        "Cookie": f"{COOKIE}={response.cookies.get(COOKIE)}",
        "X-CSRF-Token": response.json()["csrf_token"],
    }


async def audit_and_keys(engine: AsyncEngine) -> tuple[list[Any], list[str]]:
    async with AsyncSession(engine) as db:
        audit = list(
            (await db.execute(text("SELECT event, ip, details::text FROM audit_events"))).all()
        )
        keys = list((await db.execute(text("SELECT key FROM rate_limit_counters"))).scalars())
    return audit, keys


async def test_sec_18_m2_ac21_no_address_in_audit_counters_or_logs_on_every_m1_path(
    engine: AsyncEngine, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    app = make_app(engine, clock)
    async with http(app) as c:
        demo = await post(c, "/v1/demo/start", {"id_token": token("d1", "anonymous", clock)})
        assert demo.status_code == 200  # demo.started
        auth = session_headers(demo)
        wrong = await post(c, "/v1/demo/start", {"id_token": token("p1", "password", clock)})
        assert wrong.status_code == 401  # demo.denied (provider)
        unverified = await post(
            c,
            "/v1/auth/session",
            {"id_token": token("u1", "password", clock, email="u1@example.test")},
        )
        assert unverified.status_code == 403  # auth.session.denied
        ok = await post(c, "/v1/auth/session", {"id_token": verified("r1", clock)})
        assert ok.status_code == 200  # auth.session.created
        mismatch = await post(c, "/v1/auth/convert", {"id_token": verified("zz", clock)}, auth)
        assert mismatch.status_code == 401  # auth.session.denied (uid mismatch)
        converted = await post(c, "/v1/auth/convert", {"id_token": verified("d1", clock)}, auth)
        assert converted.status_code == 200  # auth.account.converted
        revoked = await post(c, "/v1/auth/sessions/revoke-all", None, session_headers(converted))
        assert revoked.status_code == 200  # auth.sessions.revoked_all
        relogin = await post(c, "/v1/auth/session", {"id_token": verified("r1", clock)})
        out = await post(c, "/v1/auth/logout", None, session_headers(relogin))
        assert out.status_code == 204  # auth.session.revoked
    app.state.token_verifier.close()

    audit, keys = await audit_and_keys(engine)
    events = {r[0] for r in audit}
    assert {
        "demo.started",
        "demo.denied",
        "auth.session.created",
        "auth.session.denied",
        "auth.account.converted",
        "auth.sessions.revoked_all",
        "auth.session.revoked",
    } <= events
    assert all(r[1] is None for r in audit)  # the ip column stays NULL
    blob = json.dumps([list(r) for r in audit], default=str) + " ".join(keys)
    for needle in (ADDRESS, SPOOF, "203.0.113", "198.51.100", "unknown"):
        assert needle not in blob
    assert keys
    assert all(k.startswith("demo:client:") for k in keys)

    logged = caplog.text + "\n".join(
        JsonFormatter("api").format(r) + repr(r.__dict__) for r in caplog.records
    )
    for needle in (ADDRESS, SPOOF, "203.0.113", "198.51.100", "x-ks-client-ip", "x-forwarded-for"):
        assert needle not in logged.lower()


async def test_sec_18_m2_ac21_demo_start_returns_429_with_the_hashed_key(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(engine, clock, demo_start_limit=2)
    async with http(app) as c:
        for i in range(2):
            ok = await post(c, "/v1/demo/start", {"id_token": token(f"h{i}", "anonymous", clock)})
            assert ok.status_code == 200
        third = await post(c, "/v1/demo/start", {"id_token": token("h2", "anonymous", clock)})
        assert (third.status_code, third.json()["error"]["code"]) == (429, "RATE_LIMITED")
        other = await c.post(
            "/v1/demo/start",
            json={"id_token": token("h3", "anonymous", clock)},
            headers={**PROXY, "X-KS-Client-IP": OTHER, "Origin": ORIGIN},
        )
        assert other.status_code == 200  # a different address has its own bucket
    app.state.token_verifier.close()
    _, keys = await audit_and_keys(engine)
    expected = hmac.new(PEPPER.encode(), ADDRESS.encode(), hashlib.sha256).hexdigest()
    assert f"demo:client:{expected}" in keys
    assert len(set(keys)) == 2


async def test_sec_18_old_counter_rows_for_a_key_expire_after_their_window(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(engine, clock, demo_start_window_seconds=60)
    async with http(app) as c:
        await post(c, "/v1/demo/start", {"id_token": token("e1", "anonymous", clock)})
        clock.advance(seconds=120)  # window over, inside the 15-minute grace: row is kept
        await post(c, "/v1/demo/start", {"id_token": token("e2", "anonymous", clock)})
        async with AsyncSession(engine) as db:
            kept = (await db.execute(text("SELECT count(*) FROM rate_limit_counters"))).scalar_one()
        assert kept == 2
        clock.advance(seconds=EXPIRY_GRACE_SECONDS + 60)
        await post(c, "/v1/demo/start", {"id_token": token("e3", "anonymous", clock)})
    app.state.token_verifier.close()
    async with AsyncSession(engine) as db:
        count = (await db.execute(text("SELECT count(*) FROM rate_limit_counters"))).scalar_one()
    assert count == 1  # both older rows expired; only the current window's row remains


def test_sec_18_bucket_key_is_keyed_and_contains_no_address() -> None:
    a = client_bucket_key(ADDRESS, b"pepper-one-0123456789")
    assert a == client_bucket_key(ADDRESS, b"pepper-one-0123456789")
    assert a != client_bucket_key(ADDRESS, b"pepper-two-0123456789")
    assert a != client_bucket_key(OTHER, b"pepper-one-0123456789")
    assert ADDRESS not in a


def test_sec_18_log_redaction_masks_address_like_keys() -> None:
    masked = redact({"client_ip": ADDRESS, "ip": ADDRESS, "x_forwarded_for": SPOOF, "count": 3})
    assert masked == {
        "client_ip": "[REDACTED]",
        "ip": "[REDACTED]",
        "x_forwarded_for": "[REDACTED]",
        "count": 3,
    }


def test_sec_18_production_requires_the_pepper_and_local_falls_back() -> None:
    values = base_values()
    values.pop("ip_hash_pepper")
    values.pop("firebase_auth_emulator_host")
    prod = Settings(_env_file=None, env="production", **values)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="KS_IP_HASH_PEPPER"):
        _ip_hash_pepper(prod)
    short = Settings(_env_file=None, env="production", ip_hash_pepper="short", **values)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="at least 16"):
        _ip_hash_pepper(short)
    local = Settings(_env_file=None, **values)  # type: ignore[call-arg]
    assert len(_ip_hash_pepper(local)) == 32
    assert _ip_hash_pepper(local) != _ip_hash_pepper(local)  # random, never persisted


async def test_sec_18_spike_echo_hides_the_address_in_production(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(
        engine,
        clock,
        env="production",
        firebase_auth_emulator_host=None,
        enable_spike_endpoints=True,
        object_store="r2",
        r2_endpoint="https://r2.example.test",
        r2_bucket="b",
        r2_access_key_id="k",
        r2_secret_access_key="s",
    )
    async with http(app) as c:
        r = await c.get("/v1/spike/echo", headers=PROXY)
    assert r.json() == {"cookie_present": False, "client_ip": None}
