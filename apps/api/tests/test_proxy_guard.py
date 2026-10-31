"""OPEN-21 / SEC-13: the API rejects direct Cloud Run access that lacks the proxy secret.

Contract: docs/contracts/proxy.md. These tests need no database (a dead engine URL is used and
only health-readiness and guard behavior are exercised).
"""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi import FastAPI, Request

from knowserve_api.app import create_app
from knowserve_api.proxy_guard import parse_client_ip
from knowserve_core.db import create_engine
from knowserve_core.settings import Settings

pytestmark = [pytest.mark.m0, pytest.mark.api]

DEAD_URL = "postgresql+asyncpg://x:y@127.0.0.1:1/none"
SECRET = "local-only-proxy-secret-not-a-secret"
HEADERS = {"X-KS-Proxy-Secret": SECRET}


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": DEAD_URL,
        "env": "local",
        "proxy_shared_secret": SECRET,
        "enable_spike_endpoints": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _app(**overrides: object) -> FastAPI:
    app = create_app(_settings(**overrides), create_engine(DEAD_URL, null_pool=True))

    @app.get("/probe-ip")
    async def probe_ip(request: Request) -> dict[str, str | None]:
        return {"client_ip": request.state.client_ip}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://api.test")


async def test_open21_direct_request_without_secret_is_rejected_with_envelope() -> None:
    async with _client(_app()) as client:
        response = await client.get("/v1/status")
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "DIRECT_ACCESS_DENIED"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert SECRET not in response.text


@pytest.mark.parametrize("supplied", ["", "wrong", SECRET + "x", SECRET[:-1], SECRET.upper()])
async def test_open21_wrong_or_partial_secret_is_rejected(supplied: str) -> None:
    async with _client(_app()) as client:
        response = await client.get("/v1/status", headers={"X-KS-Proxy-Secret": supplied})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DIRECT_ACCESS_DENIED"


async def test_open21_correct_secret_reaches_the_route() -> None:
    async with _client(_app()) as client:
        response = await client.get("/v1/status", headers=HEADERS)
    # The route ran: the dead database now produces the route's own 503, not the guard's 403.
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


async def test_open21_health_probes_stay_open_for_cloud_run() -> None:
    async with _client(_app()) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 503  # reached the readiness check (dead DB), not the guard


async def test_open21_unknown_paths_and_preflight_do_not_leak_without_the_secret() -> None:
    async with _client(_app()) as client:
        unknown = await client.get("/nope")
        spike = await client.get("/v1/spike/stream")
        preflight = await client.options(
            "/v1/status",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
    assert unknown.status_code == 403  # not 404: route existence is not revealed
    assert spike.status_code == 403
    assert preflight.status_code == 403
    assert "access-control-allow-origin" not in preflight.headers


async def test_open21_client_ip_is_trusted_only_after_the_secret_check() -> None:
    async with _client(_app()) as client:
        trusted = await client.get(
            "/probe-ip", headers={**HEADERS, "X-KS-Client-IP": "203.0.113.7"}
        )
        invalid = await client.get("/probe-ip", headers={**HEADERS, "X-KS-Client-IP": "not-an-ip"})
        absent = await client.get("/probe-ip", headers=HEADERS)
        spoofed = await client.get("/probe-ip", headers={"X-KS-Client-IP": "203.0.113.7"})
    assert trusted.json() == {"client_ip": "203.0.113.7"}
    assert invalid.json() == {"client_ip": None}
    assert absent.json() == {"client_ip": None}
    assert spoofed.status_code == 403


def test_open21_parse_client_ip_accepts_v4_and_v6_and_rejects_garbage() -> None:
    assert parse_client_ip("203.0.113.7") == "203.0.113.7"
    assert parse_client_ip(" 2001:db8::1 ") == "2001:db8::1"
    assert parse_client_ip("203.0.113.7, 10.0.0.1") is None
    assert parse_client_ip("") is None
    assert parse_client_ip(None) is None


async def test_open21_empty_secret_setting_means_guard_off_outside_production() -> None:
    async with _client(_app(proxy_shared_secret="")) as client:
        response = await client.get("/v1/status")
    assert response.status_code == 503  # reached the route, no guard


def test_open21_production_refuses_to_start_without_the_proxy_secret() -> None:
    with pytest.raises(RuntimeError, match="KS_PROXY_SHARED_SECRET"):
        create_app(_settings(env="production", proxy_shared_secret=None))
    with pytest.raises(RuntimeError, match="KS_PROXY_SHARED_SECRET"):
        create_app(_settings(env="production", proxy_shared_secret=""))


async def test_open21_production_starts_and_enforces_with_the_secret() -> None:
    app = create_app(
        _settings(env="production", enable_spike_endpoints=False),
        create_engine(DEAD_URL, null_pool=True),
    )
    async with _client(app) as client:
        denied = await client.get("/v1/status")
    assert denied.status_code == 403


async def test_open21_secret_never_appears_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    async with _client(_app()) as client:
        await client.get("/v1/status", headers={"X-KS-Proxy-Secret": "attacker-guess"})
        await client.get("/v1/status", headers=HEADERS)
    assert SECRET not in caplog.text
    assert "attacker-guess" not in caplog.text


async def test_open21_spike_echo_reports_the_forwarded_client_ip_only_with_the_secret() -> None:
    async with _client(_app()) as client:
        shown = await client.get(
            "/v1/spike/echo", headers={**HEADERS, "X-KS-Client-IP": "203.0.113.7"}
        )
        garbage = await client.get("/v1/spike/echo", headers={**HEADERS, "X-KS-Client-IP": "nope"})
        denied = await client.get("/v1/spike/echo", headers={"X-KS-Client-IP": "203.0.113.7"})
    assert shown.json() == {"cookie_present": False, "client_ip": "203.0.113.7"}
    assert garbage.json() == {"cookie_present": False, "client_ip": None}
    assert denied.status_code == 403 and "203.0.113.7" not in denied.text
