"""M1-01: the API contract stubs (M1-AC10). Slices replace the 501 stubs with real behavior."""

import pytest
from fastapi.testclient import TestClient

from knowserve_api.app import create_app
from knowserve_core.settings import Settings

pytestmark = [pytest.mark.m1, pytest.mark.api]

M1_ROUTES = {
    ("post", "/v1/auth/session"),
    ("post", "/v1/auth/convert"),
    ("post", "/v1/auth/logout"),
    ("get", "/v1/auth/me"),
    ("post", "/v1/auth/sessions/revoke-all"),
    ("post", "/v1/demo/start"),
    ("get", "/v1/departments"),
    ("put", "/v1/session/department"),
    ("get", "/v1/admin/ping"),
}


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        env="local",
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_m1_ac10_openapi_lists_every_m1_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    found = {(method, path) for path, ops in paths.items() for method in ops}
    assert M1_ROUTES <= found


def test_m1_ac10_stubs_return_the_error_envelope_with_a_request_id(client: TestClient) -> None:
    token = {"id_token": "x" * 40}
    response = client.post("/v1/auth/session", json=token)
    assert response.status_code == 501
    body = response.json()["error"]
    assert body["code"] == "NOT_IMPLEMENTED"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_m1_ac10_validation_errors_use_the_envelope(client: TestClient) -> None:
    response = client.post("/v1/auth/session", json={"id_token": "short"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_m1_api_refuses_production_without_a_firebase_project() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        env="production",
        api_allowed_origins=["https://app.example.test"],
        proxy_shared_secret="s" * 32,  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="KS_FIREBASE_PROJECT_ID"):
        create_app(settings)
