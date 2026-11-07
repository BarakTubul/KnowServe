"""M2-01: document route contract stubs (M2-AC14). M2-02 and M2-03 replace the 501 bodies."""

import pytest
from fastapi.testclient import TestClient

from knowserve_api.app import create_app
from knowserve_core.settings import Settings

pytestmark = [pytest.mark.m2, pytest.mark.documents, pytest.mark.api]

M2_ROUTES = {
    ("get", "/v1/documents"),
    ("get", "/v1/documents/{document_id}"),
    ("get", "/v1/documents/{document_id}/content"),
}


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@localhost/db",
        env="local",
    )
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_m2_ac14_openapi_lists_the_document_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    found = {(method, path) for path, ops in paths.items() for method in ops}
    assert M2_ROUTES <= found


def test_m2_ac14_list_response_is_a_cursor_page(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    page = schemas["DocumentListResponse"]["properties"]
    assert set(page) == {"items", "next_cursor", "has_more"}
    assert "total" not in page


@pytest.mark.parametrize(
    "path",
    ["/v1/documents", "/v1/documents/x", "/v1/documents/x/content"],
)
def test_sec06_document_routes_require_a_session(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
