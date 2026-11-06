"""M1-08 review follow-ups: SEC-13 database outage, AUTH-18 and AUTH-29 static guards."""

from pathlib import Path

import httpx
import pytest

from knowserve_api.app import create_app
from knowserve_api.auth.service import ALLOWED_PROVIDERS
from knowserve_core.db import create_engine
from knowserve_core.settings import Settings
from knowserve_core.testing import mint_emulator_token

pytestmark = pytest.mark.m1

DEAD_URL = "postgresql+asyncpg://knowserve:pw@127.0.0.1:1/none"
ROOT = Path(__file__).resolve().parents[3]


def _dead_db_app():
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,  # type: ignore[call-arg]
        database_url=DEAD_URL,
        env="local",
        firebase_project_id="demo-knowserve",
        firebase_auth_emulator_host="localhost:9099",
    )
    return create_app(settings, create_engine(DEAD_URL, null_pool=True))


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://api.test")


async def test_sec13_database_down_session_lookup_is_503_never_200() -> None:
    async with _client(_dead_db_app()) as client:
        response = await client.get("/v1/auth/me", cookies={"ks_session": "some-token"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"


async def test_sec13_database_down_session_exchange_fails_closed_with_503() -> None:
    token = mint_emulator_token("uid-x", email="x@example.test", email_verified=True)
    async with _client(_dead_db_app()) as client:
        response = await client.post(
            "/v1/auth/session",
            json={"id_token": token},
            headers={"Origin": "http://localhost:5173"},
        )
    assert response.status_code == 503
    assert "set-cookie" not in response.headers


def _source_files() -> list[Path]:
    files: list[Path] = []
    for base in ("apps/api/src", "apps/worker/src", "packages/backend_core/src"):
        files += [p for p in (ROOT / base).rglob("*.py")]
    return files


def test_auth18_no_session_middleware_and_no_jwt_session_issuing_in_target_code() -> None:
    offenders = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        if "SessionMiddleware" in text or "python-jose" in text or "jwt.encode(" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_auth29_only_password_and_google_may_create_a_registered_session() -> None:
    """Anonymous is for Try Demo only (its own route); no email-link or OTP provider exists."""
    assert ALLOWED_PROVIDERS == frozenset({"password", "google.com"})
    for path in _source_files():
        text = path.read_text(encoding="utf-8").lower()
        assert "emaillink" not in text and "email_link" not in text, path.name
