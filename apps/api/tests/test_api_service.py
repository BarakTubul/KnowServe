"""M0-AC14 (API side) and M0-AC06 (export side): the API service baseline.

Requirement ids: ARCH-05 (error envelope), ARCH-09/MON-03/MON-05 (JSON logs, no secrets),
ARCH-12 (config), ARCH-13 (health/ready), INFRA-01 (service runs).
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_api.app import create_app
from knowserve_api.export_openapi import build_schema
from knowserve_core.db import create_engine
from knowserve_core.logging import configure_logging
from knowserve_core.settings import Settings

pytestmark = [pytest.mark.m0, pytest.mark.api]

ORIGIN = "http://localhost:5173"
BAD_ORIGIN = "http://evil.example"
DEAD_URL = "postgresql+asyncpg://knowserve:pw@127.0.0.1:1/none"
OPENAPI_PATH = Path(__file__).resolve().parents[3] / "docs" / "contracts" / "openapi.json"


def _settings(url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "database_url": url,
        "env": "ci",
        "api_allowed_origins": [ORIGIN],
        "enable_spike_endpoints": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="https://test")


@pytest_asyncio.fixture
async def dead_app() -> AsyncIterator[FastAPI]:
    engine = create_engine(DEAD_URL, null_pool=True)
    yield create_app(_settings(DEAD_URL), engine)
    await engine.dispose()


@pytest.fixture
def live_app_factory(engine: AsyncEngine, database_url: str) -> Callable[..., FastAPI]:
    def make(**overrides: object) -> FastAPI:
        return create_app(_settings(database_url, **overrides), engine)

    return make


# ---------------------------------------------------------------- health / status


async def test_arch_13_health_live_needs_no_dependencies(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
async def test_arch_13_health_ready_200_with_database(
    live_app_factory: Callable[..., FastAPI],
) -> None:
    async with _client(live_app_factory()) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_arch_13_health_ready_503_envelope_when_database_down(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/health/ready", headers={"X-Request-ID": "req_ready_down_1"})
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DEPENDENCY_UNAVAILABLE"
    assert error["request_id"] == "req_ready_down_1"
    assert "127.0.0.1" not in response.text
    assert "pw" not in json.dumps(error).split()


@pytest.mark.integration
async def test_m0_ac14_status_200_with_database(live_app_factory: Callable[..., FastAPI]) -> None:
    async with _client(live_app_factory(env="ci")) as client:
        response = await client.get("/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "api"
    assert body["environment"] == "ci"
    assert body["database"] == "ok"
    assert isinstance(body["version"], str) and body["version"]


async def test_m0_ac14_status_503_envelope_when_database_down(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/v1/status")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


# ---------------------------------------------------------------- error envelope


def _app_with_probe_routes(app: FastAPI) -> FastAPI:
    """Throwaway routes live only in the test app; the real API surface is unchanged."""

    @app.get("/_probe/int")
    async def probe_int(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get("/_probe/boom")
    async def probe_boom() -> None:
        raise RuntimeError("super secret internal detail")

    return app


async def test_arch_05_unknown_route_404_envelope(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/nope")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_arch_05_wrong_method_405_envelope(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.post("/health/live")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_arch_05_invalid_input_422_envelope_with_details(dead_app: FastAPI) -> None:
    async with _client(_app_with_probe_routes(dead_app)) as client:
        response = await client.get("/_probe/int", params={"n": "abc"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_arch_05_unexpected_exception_500_generic_without_traceback(
    dead_app: FastAPI,
) -> None:
    async with _client(_app_with_probe_routes(dead_app)) as client:
        response = await client.get("/_probe/boom")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert "super secret" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]


# ---------------------------------------------------------------- request ids


async def test_arch_05_request_id_accepted_and_echoed(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        ok = await client.get("/health/live", headers={"X-Request-ID": "client-id_01.x"})
        err = await client.get("/nope", headers={"X-Request-ID": "client-id_02.x"})
    assert ok.headers["X-Request-ID"] == "client-id_01.x"
    assert err.headers["X-Request-ID"] == "client-id_02.x"
    assert err.json()["error"]["request_id"] == "client-id_02.x"


@pytest.mark.parametrize("bad", ["short", "has spaces in it!", "x" * 65, "semi;colon-id"])
async def test_arch_05_invalid_request_id_replaced_by_generated(
    dead_app: FastAPI, bad: str
) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/nope", headers={"X-Request-ID": bad})
    generated = response.headers["X-Request-ID"]
    assert generated != bad
    assert generated.startswith("req_") and len(generated) == 4 + 16
    assert response.json()["error"]["request_id"] == generated


async def test_arch_05_request_id_generated_when_absent(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        first = await client.get("/health/live")
        second = await client.get("/health/live")
    assert first.headers["X-Request-ID"].startswith("req_")
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


# ---------------------------------------------------------------- CORS


async def test_arch_12_cors_allowed_origin_gets_credentials(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/health/live", headers={"Origin": ORIGIN})
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()


async def test_arch_12_cors_disallowed_origin_gets_no_headers(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.get("/health/live", headers={"Origin": BAD_ORIGIN})
    assert "access-control-allow-origin" not in response.headers


async def test_arch_12_cors_preflight_works_for_allowed_origin(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.options(
            "/v1/status",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Request-ID",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-request-id" in response.headers["access-control-allow-headers"].lower()


async def test_arch_12_cors_preflight_rejected_for_disallowed_origin(dead_app: FastAPI) -> None:
    async with _client(dead_app) as client:
        response = await client.options(
            "/v1/status",
            headers={"Origin": BAD_ORIGIN, "Access-Control-Request-Method": "GET"},
        )
    assert "access-control-allow-origin" not in response.headers


# ---------------------------------------------------------------- spike endpoints


async def test_m0_08_spike_disabled_returns_404_envelope_and_not_in_openapi(
    dead_app: FastAPI,
) -> None:
    async with _client(dead_app) as client:
        cookie = await client.post("/v1/spike/cookie")
        echo = await client.get("/v1/spike/echo")
    for response in (cookie, echo):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"
        assert "set-cookie" not in response.headers
    assert not [p for p in dead_app.openapi()["paths"] if "spike" in p]


async def test_m0_08_spike_enabled_sets_host_only_cookie_with_exact_flags() -> None:
    engine = create_engine(DEAD_URL, null_pool=True)
    app = create_app(_settings(DEAD_URL, enable_spike_endpoints=True), engine)
    try:
        async with _client(app) as client:
            response = await client.post("/v1/spike/cookie")
    finally:
        await engine.dispose()
    assert response.status_code == 204
    header = response.headers["set-cookie"]
    attrs = [part.strip() for part in header.split(";")]
    assert attrs[0] == "ks_spike=1"
    lowered = {a.lower() for a in attrs[1:]}
    assert lowered == {"secure", "httponly", "samesite=lax", "path=/", "max-age=300"}
    assert "domain" not in header.lower()
    assert any("spike" in p for p in app.openapi()["paths"])


async def test_m0_08_spike_echo_reflects_cookie_presence() -> None:
    engine = create_engine(DEAD_URL, null_pool=True)
    app = create_app(_settings(DEAD_URL, enable_spike_endpoints=True), engine)
    try:
        async with _client(app) as client:
            absent = await client.get("/v1/spike/echo")
            present = await client.get("/v1/spike/echo", headers={"Cookie": "ks_spike=1"})
    finally:
        await engine.dispose()
    assert absent.json() == {"cookie_present": False}
    assert present.json() == {"cookie_present": True}


# ---------------------------------------------------------------- logging


async def test_mon_03_mon_05_logs_are_json_with_request_id_and_no_secrets() -> None:
    secret_url = "postgresql+asyncpg://knowserve:hunter2-db-password@127.0.0.1:1/none"
    engine = create_engine(secret_url, null_pool=True)
    app = _app_with_probe_routes(create_app(_settings(secret_url), engine))
    stream = io.StringIO()
    configure_logging("api", "DEBUG", stream)  # capture after create_app configured stdout
    try:
        async with _client(app) as client:
            await client.get("/health/ready", headers={"X-Request-ID": "req_log_capture_1"})
            await client.get(
                "/_probe/boom",
                headers={
                    "X-Request-ID": "req_log_capture_2",
                    "Authorization": "Bearer top-secret-token-value",
                    "Cookie": "session=sess-secret-value",
                },
            )
    finally:
        await engine.dispose()
        logging.getLogger().handlers.clear()
    raw = stream.getvalue()
    lines = [line for line in raw.splitlines() if line.strip()]
    assert lines, "expected log output"
    records = [json.loads(line) for line in lines]  # every line is JSON
    for record in records:
        assert {"timestamp", "severity", "service", "message", "request_id"} <= record.keys()
        assert record["service"] == "api"
    assert any(r["request_id"] == "req_log_capture_2" for r in records)
    for secret in ("hunter2-db-password", "top-secret-token-value", "sess-secret-value"):
        assert secret not in raw


# ---------------------------------------------------------------- OpenAPI export


def test_m0_ac06_export_matches_committed_openapi_baseline() -> None:
    generated = json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"
    assert generated == OPENAPI_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_m0_ac06_export_is_deterministic_and_has_no_spike_paths() -> None:
    first = json.dumps(build_schema(), sort_keys=True)
    second = json.dumps(build_schema(), sort_keys=True)
    assert first == second
    assert not [p for p in build_schema()["paths"] if "spike" in p]
