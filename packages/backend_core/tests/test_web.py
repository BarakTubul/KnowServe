"""ARCH-05: the standard error envelope and request-id propagation."""

import httpx
import pytest
from fastapi import FastAPI

from knowserve_core.web import AppError, install_web


def _app() -> FastAPI:
    app = FastAPI()
    install_web(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    @app.get("/conflict")
    async def conflict() -> None:
        raise AppError(409, "ACTIVE_DEPARTMENT_REQUIRED", "Select a department first")

    @app.get("/needs-int")
    async def needs_int(n: int) -> dict[str, int]:
        return {"n": n}

    return app


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.m0
async def test_arch_05_unknown_route_uses_envelope_with_request_id() -> None:
    async with _client() as client:
        response = await client.get("/nope", headers={"X-Request-ID": "req_client_supplied1"})
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"] == "req_client_supplied1"
    assert response.headers["X-Request-ID"] == "req_client_supplied1"


@pytest.mark.m0
async def test_arch_05_validation_error_is_422_with_details() -> None:
    async with _client() as client:
        response = await client.get("/needs-int", params={"n": "abc"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["loc"][-1] == "n"


@pytest.mark.m0
async def test_arch_05_app_error_keeps_its_status_and_code() -> None:
    async with _client() as client:
        response = await client.get("/conflict")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_DEPARTMENT_REQUIRED"


@pytest.mark.m0
async def test_arch_05_unexpected_error_is_generic_500_without_leaks() -> None:
    async with _client() as client:
        response = await client.get("/boom")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text


@pytest.mark.m0
async def test_arch_05_malformed_inbound_request_id_is_replaced() -> None:
    async with _client() as client:
        response = await client.get("/nope", headers={"X-Request-ID": "bad id with spaces"})
    assert response.json()["error"]["request_id"].startswith("req_")
