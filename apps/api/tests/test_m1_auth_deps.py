"""M1-02a: identity dependencies, CSRF/Origin, cookie helpers and error mapping.

The real routes arrive in M1-02b. Here a throwaway router, added to a test-built app only (never to
``create_app`` or the OpenAPI snapshot), exercises the dependencies through real HTTP-shaped calls
against the real session service and database.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from knowserve_api.app import create_app
from knowserve_api.auth.deps import (
    clear_session_cookie,
    get_clock,
    get_db,
    get_identity,
    get_session_service,
    get_settings_dep,
    get_token_verifier,
    require_active_department,
    require_admin,
    require_csrf,
    require_origin,
    require_registered,
    set_session_cookie,
)
from knowserve_api.auth.verification import verify_id_token_or_raise
from knowserve_api.schemas import IdTokenRequest
from knowserve_core.clock import Clock, FakeClock
from knowserve_core.firebase_tokens import (
    FakeTokenVerifier,
    InvalidToken,
    StaleSignIn,
    TokenVerifier,
    VerifierUnavailable,
)
from knowserve_core.firebase_verifier import EMULATOR_ENV_VAR, FirebaseTokenVerifier
from knowserve_core.identity import Identity
from knowserve_core.models import Session, User
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.sessions import SessionService
from knowserve_core.settings import Settings
from knowserve_core.testing import DEFAULT_PROJECT_ID, mint_emulator_token

pytestmark = [pytest.mark.m1, pytest.mark.api, pytest.mark.integration]

ORIGIN = "http://localhost:5173"
COOKIE = "ks_session"


@pytest.fixture(autouse=True)
def _restore_emulator_env() -> Iterator[None]:
    """The verifier exports the SDK's emulator variable (process-wide); never leak it."""
    saved = os.environ.get(EMULATOR_ENV_VAR)
    yield
    if saved is None:
        os.environ.pop(EMULATOR_ENV_VAR, None)
    else:
        os.environ[EMULATOR_ENV_VAR] = saved


router = APIRouter(prefix="/_t")


@router.get("/me")
async def t_me(identity: Annotated[Identity, Depends(get_identity)]) -> dict[str, Any]:
    return {"kind": identity.kind, "session_id": str(identity.session_id)}


@router.get("/registered")
async def t_registered(identity: Annotated[Identity, Depends(require_registered)]) -> dict:
    return {"kind": identity.kind}


@router.get("/admin")
async def t_admin(identity: Annotated[Identity, Depends(require_admin)]) -> dict:
    return {"kind": identity.kind}


@router.get("/dept")
async def t_dept(identity: Annotated[Identity, Depends(require_active_department)]) -> dict:
    return {"department": str(identity.active_department_id)}


@router.get("/read")
@router.post("/mutate")
@router.put("/mutate")
@router.patch("/mutate")
@router.delete("/mutate")
async def t_csrf(identity: Annotated[Identity, Depends(require_csrf)]) -> dict:
    return {"ok": True}


@router.post("/origin-only")
async def t_origin(_: Annotated[None, Depends(require_origin)]) -> dict:
    return {"ok": True}


@router.post("/verify")
async def t_verify(
    body: IdTokenRequest,
    request_verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> dict:
    verified = await verify_id_token_or_raise(request_verifier, body.id_token)
    return {"uid": verified.uid, "provider": verified.sign_in_provider}


@router.post("/login/{user_id}")
async def t_login(
    user_id: uuid.UUID,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[SessionService, Depends(get_session_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> dict:
    user = await db.get(User, user_id)
    assert user is not None
    token, row = await service.create_session(db, user, "password")
    await db.commit()
    set_session_cookie(response, settings, token, row.expires_at, clock.now())
    return {"session_id": str(row.id), "csrf_token": row.csrf_secret, "token": token}


@router.post("/logout")
async def t_logout(response: Response, settings: Annotated[Settings, Depends(get_settings_dep)]):
    clear_session_cookie(response, settings)
    return {"ok": True}


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_project_id": DEFAULT_PROJECT_ID,
        "firebase_auth_emulator_host": "localhost:9099",
        "api_allowed_origins": [ORIGIN],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture
def verifier_double() -> FakeTokenVerifier:
    return FakeTokenVerifier()


def build_app(engine: AsyncEngine, clock: FakeClock, verifier: Any, **settings: Any) -> FastAPI:
    app = create_app(
        make_settings(**settings),
        engine=engine,
        token_verifier=verifier,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
    )
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def client(
    engine: AsyncEngine, clock: FakeClock, verifier_double: FakeTokenVerifier
) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(engine, clock, verifier_double)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as c:
        yield c


def cookie_header(token: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE}={token}"}


def code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


# --- AUTH-10 / identity ------------------------------------------------------------------------


async def test_auth_10_no_cookie_is_401_unauthenticated(client: httpx.AsyncClient) -> None:
    response = await client.get("/_t/me")
    assert response.status_code == 401
    assert code(response) == "UNAUTHENTICATED"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


async def test_auth_10_garbage_cookie_is_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/_t/me", headers=cookie_header("not-a-session"))
    assert response.status_code == 401 and code(response) == "UNAUTHENTICATED"


async def test_auth_10_session_expires_exactly_24_hours_after_creation(
    client: httpx.AsyncClient, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    login = (await client.post(f"/_t/login/{user.id}", headers={"Origin": ORIGIN})).json()
    headers = cookie_header(login["token"])

    clock.advance(hours=23, minutes=59, seconds=59)
    assert (await client.get("/_t/me", headers=headers)).status_code == 200
    clock.advance(seconds=1)
    expired = await client.get("/_t/me", headers=headers)
    assert expired.status_code == 401 and code(expired) == "UNAUTHENTICATED"
    clock.advance(seconds=1)
    assert (await client.get("/_t/me", headers=headers)).status_code == 401


async def test_auth_10_activity_does_not_extend_the_session(
    client: httpx.AsyncClient, clock: FakeClock, engine: AsyncEngine, make_user
) -> None:
    user = await make_user("registered")
    login = (await client.post(f"/_t/login/{user.id}")).json()
    headers = cookie_header(login["token"])
    async with AsyncSession(engine) as db:
        before = await db.scalar(select(Session.expires_at).where(Session.token_hash != ""))
    for _ in range(11):
        clock.advance(hours=2)
        assert (await client.get("/_t/me", headers=headers)).status_code == 200
    async with AsyncSession(engine) as db:
        after = await db.scalar(select(Session.expires_at).where(Session.token_hash != ""))
    assert before == after
    clock.advance(hours=2)  # 24 h since creation despite constant use
    assert (await client.get("/_t/me", headers=headers)).status_code == 401


async def test_auth_10_there_is_no_refresh_route(client: httpx.AsyncClient, make_user) -> None:
    app: FastAPI = client._transport.app  # type: ignore[attr-defined]
    paths = {getattr(route, "path", "") for route in app.routes}
    assert not [p for p in paths if "refresh" in p or "renew" in p or "extend" in p]
    user = await make_user("registered")
    login = (await client.post(f"/_t/login/{user.id}")).json()
    for path in ("/v1/auth/refresh", "/v1/session/refresh", "/v1/auth/renew"):
        response = await client.post(
            path, headers={**cookie_header(login["token"]), "Origin": ORIGIN}
        )
        assert response.status_code in (404, 405)


async def test_auth_10_revoked_session_is_401(
    client: httpx.AsyncClient, engine: AsyncEngine, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    login = (await client.post(f"/_t/login/{user.id}")).json()
    async with AsyncSession(engine) as db:
        await db.execute(text("UPDATE sessions SET revoked_at = :now"), {"now": clock.now()})
        await db.commit()
    response = await client.get("/_t/me", headers=cookie_header(login["token"]))
    assert response.status_code == 401


async def test_auth_10_disabled_user_session_is_401(
    client: httpx.AsyncClient, engine: AsyncEngine, clock: FakeClock, make_user
) -> None:
    user = await make_user("registered")
    login = (await client.post(f"/_t/login/{user.id}")).json()
    headers = cookie_header(login["token"])
    assert (await client.get("/_t/me", headers=headers)).status_code == 200
    async with AsyncSession(engine) as db:
        await db.execute(
            text("UPDATE users SET disabled_at = :now WHERE id = :id"),
            {"now": clock.now(), "id": user.id},
        )
        await db.commit()
    response = await client.get("/_t/me", headers=headers)
    assert response.status_code == 401 and code(response) == "UNAUTHENTICATED"


# --- roles and department ----------------------------------------------------------------------


async def test_sec_03_role_dependencies(client: httpx.AsyncClient, make_user, make_session) -> None:
    demo = await make_session(await make_user("demo"), provider="anonymous")
    registered = await make_session(await make_user("registered"))
    admin = await make_session(await make_user("admin"))

    def get(path: str, handle):
        return client.get(path, headers=cookie_header(handle.cookie))

    assert (await get("/_t/registered", demo)).status_code == 403
    assert code(await get("/_t/registered", demo)) == "FORBIDDEN"
    assert (await get("/_t/registered", registered)).status_code == 200
    assert (await get("/_t/registered", admin)).status_code == 200

    assert (await get("/_t/admin", demo)).status_code == 403
    assert (await get("/_t/admin", registered)).status_code == 403
    assert (await get("/_t/admin", admin)).status_code == 200
    assert (await client.get("/_t/admin")).status_code == 401


async def test_sec_03_admin_is_decided_by_users_kind_only(
    client: httpx.AsyncClient, make_user, make_session, session_factory
) -> None:
    """An admin-looking email or uid on a registered user grants nothing (AUTH-04)."""
    user = await make_user("registered", uid="admin", email="admin@example.test")
    handle = await make_session(user)
    headers = {**cookie_header(handle.cookie), "X-Admin": "true", "X-Forwarded-Email": user.email}
    assert (await client.get("/_t/admin", headers=headers)).status_code == 403
    async with session_factory() as db:
        await db.execute(text("UPDATE users SET kind = 'admin' WHERE id = :id"), {"id": user.id})
        await db.commit()
    assert (await client.get("/_t/admin", headers=headers)).status_code == 200


async def test_auth_17_active_department_required(
    client: httpx.AsyncClient, make_user, make_session, session_factory
) -> None:
    user = await make_user("registered")
    without = await make_session(user)
    async with session_factory() as db:
        dept = await db.scalar(text("SELECT id FROM departments LIMIT 1"))
    with_dept = await make_session(user, department_id=dept)

    response = await client.get("/_t/dept", headers=cookie_header(without.cookie))
    assert response.status_code == 409 and code(response) == "ACTIVE_DEPARTMENT_REQUIRED"
    ok = await client.get("/_t/dept", headers=cookie_header(with_dept.cookie))
    assert ok.status_code == 200 and ok.json()["department"] == str(dept)
    assert (await client.get("/_t/dept")).status_code == 401  # authentication comes first


# --- AUTH-14 -----------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_auth_14_mutations_need_csrf_and_origin(
    client: httpx.AsyncClient, make_user, make_session, method: str
) -> None:
    mine = await make_session(await make_user("registered"))
    theirs = await make_session(await make_user("registered"))
    base = cookie_header(mine.cookie)

    async def call(extra: dict[str, str]) -> httpx.Response:
        return await client.request(method, "/_t/mutate", headers={**base, **extra})

    no_token = await call({"Origin": ORIGIN})
    assert (no_token.status_code, code(no_token)) == (403, "CSRF_INVALID")
    wrong = await call({"Origin": ORIGIN, "X-CSRF-Token": "wrong"})
    assert (wrong.status_code, code(wrong)) == (403, "CSRF_INVALID")
    other_session = await call({"Origin": ORIGIN, "X-CSRF-Token": theirs.csrf_token})
    assert (other_session.status_code, code(other_session)) == (403, "CSRF_INVALID")
    foreign = await call({"Origin": "https://evil.example", "X-CSRF-Token": mine.csrf_token})
    assert (foreign.status_code, code(foreign)) == (403, "ORIGIN_INVALID")
    missing = await call({"X-CSRF-Token": mine.csrf_token})
    assert (missing.status_code, code(missing)) == (403, "ORIGIN_INVALID")
    null_origin = await call({"Origin": "null", "X-CSRF-Token": mine.csrf_token})
    assert (null_origin.status_code, code(null_origin)) == (403, "ORIGIN_INVALID")
    valid = await call({"Origin": ORIGIN, "X-CSRF-Token": mine.csrf_token})
    assert valid.status_code == 200


async def test_auth_14_csrf_without_a_session_is_401_not_403(client: httpx.AsyncClient) -> None:
    response = await client.post("/_t/mutate", headers={"Origin": ORIGIN, "X-CSRF-Token": "x"})
    assert response.status_code == 401


async def test_auth_14_safe_methods_do_not_need_csrf(
    client: httpx.AsyncClient, make_user, make_session
) -> None:
    handle = await make_session(await make_user("registered"))
    response = await client.get("/_t/read", headers=cookie_header(handle.cookie))
    assert response.status_code == 200


async def test_auth_14_allowed_origins_come_from_configuration(
    engine: AsyncEngine, clock: FakeClock, verifier_double, make_user, make_session
) -> None:
    app = build_app(
        engine, clock, verifier_double, api_allowed_origins=["https://app.example.test/"]
    )
    handle = await make_session(await make_user("registered"))
    headers = {**cookie_header(handle.cookie), "X-CSRF-Token": handle.csrf_token}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        ok = await c.post("/_t/mutate", headers={**headers, "Origin": "https://app.example.test"})
        old = await c.post("/_t/mutate", headers={**headers, "Origin": ORIGIN})
    assert ok.status_code == 200
    assert code(old) == "ORIGIN_INVALID"


async def test_auth_14_session_creating_endpoints_check_origin_only(
    client: httpx.AsyncClient,
) -> None:
    foreign = await client.post("/_t/origin-only", headers={"Origin": "https://evil.example"})
    assert (foreign.status_code, code(foreign)) == (403, "ORIGIN_INVALID")
    missing = await client.post("/_t/origin-only")
    assert (missing.status_code, code(missing)) == (403, "ORIGIN_INVALID")
    ok = await client.post("/_t/origin-only", headers={"Origin": ORIGIN})
    assert ok.status_code == 200


# --- AUTH-06 cookie ----------------------------------------------------------------------------


async def test_auth_06_cookie_attributes_and_hashed_storage(
    client: httpx.AsyncClient, engine: AsyncEngine, make_user
) -> None:
    user = await make_user("registered")
    first = await client.post(f"/_t/login/{user.id}")
    second = await client.post(f"/_t/login/{user.id}")
    set_cookie = first.headers["set-cookie"]
    lowered = set_cookie.lower()
    token = first.json()["token"]

    assert set_cookie.startswith(f"{COOKIE}={token}")
    assert "secure" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    assert "domain" not in lowered
    assert "max-age=86400" in lowered

    assert first.json()["session_id"] != second.json()["session_id"]
    assert first.json()["token"] != second.json()["token"]
    async with AsyncSession(engine) as db:
        hashes = set((await db.execute(select(Session.token_hash))).scalars())
    assert hashlib.sha256(token.encode()).hexdigest() in hashes
    assert token not in hashes


async def test_auth_06_max_age_is_the_remaining_lifetime(
    engine: AsyncEngine, clock: FakeClock, verifier_double
) -> None:
    app = build_app(engine, clock, verifier_double)
    settings = app.state.settings
    response = Response()
    now = clock.now()
    set_session_cookie(response, settings, "tok", now + timedelta(hours=1, seconds=30), now)
    assert "Max-Age=3630" in response.headers["set-cookie"]
    expired = Response()
    set_session_cookie(expired, settings, "tok", now - timedelta(seconds=5), now)
    assert "Max-Age=0" in expired.headers["set-cookie"]


async def test_auth_06_cookie_name_comes_from_configuration(
    engine: AsyncEngine, clock: FakeClock, verifier_double, make_user, make_session
) -> None:
    app = build_app(engine, clock, verifier_double, session_cookie_name="custom_sid")
    handle = await make_session(await make_user("registered"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        assert (await c.get("/_t/me", headers=cookie_header(handle.cookie))).status_code == 401
        ok = await c.get("/_t/me", headers={"Cookie": f"custom_sid={handle.cookie}"})
    assert ok.status_code == 200


async def test_auth_06_logout_cookie_clears_the_session_cookie(client: httpx.AsyncClient) -> None:
    response = await client.post("/_t/logout")
    header = response.headers["set-cookie"].lower()
    assert header.startswith(f"{COOKIE}=")
    assert "max-age=0" in header
    assert "secure" in header and "httponly" in header and "domain" not in header


# --- AUTH-07 / AUTH-30 / SEC-13 error mapping --------------------------------------------------


async def test_auth_07_error_mapping_with_a_fake_verifier(
    client: httpx.AsyncClient, verifier_double: FakeTokenVerifier
) -> None:
    verifier_double.add("t" * 30 + "invalid", InvalidToken("forged"))
    verifier_double.add("t" * 30 + "stale", StaleSignIn("old"))
    verifier_double.add("t" * 30 + "down", VerifierUnavailable("keys"))

    invalid = await client.post("/_t/verify", json={"id_token": "t" * 30 + "invalid"})
    unknown = await client.post("/_t/verify", json={"id_token": "u" * 30})
    stale = await client.post("/_t/verify", json={"id_token": "t" * 30 + "stale"})
    down = await client.post("/_t/verify", json={"id_token": "t" * 30 + "down"})

    assert (invalid.status_code, code(invalid)) == (401, "UNAUTHENTICATED")
    assert (unknown.status_code, code(unknown)) == (401, "UNAUTHENTICATED")
    assert invalid.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert (stale.status_code, code(stale)) == (401, "REAUTH_REQUIRED")
    assert (down.status_code, code(down)) == (503, "DEPENDENCY_UNAVAILABLE")


async def test_auth_07_real_verifier_through_the_api_error_mapping(
    engine: AsyncEngine, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EMULATOR_ENV_VAR, "localhost:9099")  # restored afterwards
    settings = make_settings()
    verifier = FirebaseTokenVerifier(settings, clock)
    app = build_app(engine, clock, verifier)
    now = clock.now()

    def body(**kwargs: Any) -> dict[str, str]:
        kwargs.setdefault("issued_at", now)
        return {"id_token": mint_emulator_token("uid-9", **kwargs)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        ok = await c.post("/_t/verify", json=body(provider="anonymous"))
        forged_audience = await c.post("/_t/verify", json=body(project_id="other"))
        stale_valid = await c.post("/_t/verify", json=body(auth_time=now - timedelta(hours=1)))
        stale_invalid = await c.post(
            "/_t/verify", json=body(auth_time=now - timedelta(hours=1), project_id="other")
        )
        garbage = await c.post("/_t/verify", json={"id_token": "g" * 40})
    verifier.close()

    assert ok.status_code == 200 and ok.json() == {"uid": "uid-9", "provider": "anonymous"}
    assert (forged_audience.status_code, code(forged_audience)) == (401, "UNAUTHENTICATED")
    assert (stale_valid.status_code, code(stale_valid)) == (401, "REAUTH_REQUIRED")
    assert (stale_invalid.status_code, code(stale_invalid)) == (401, "UNAUTHENTICATED")
    assert garbage.status_code == 401
    assert forged_audience.json()["error"]["message"] == garbage.json()["error"]["message"]


# --- app wiring --------------------------------------------------------------------------------


async def test_m1_create_app_wires_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EMULATOR_ENV_VAR, raising=False)
    app = create_app(make_settings(firebase_auth_emulator_host=None))
    assert isinstance(app.state.token_verifier, FirebaseTokenVerifier)
    assert isinstance(app.state.rate_limiter, PostgresRateLimiter)
    assert app.state.clock.now().tzinfo is not None
    await app.state.engine.dispose()


async def test_m1_create_app_accepts_injected_state(
    engine: AsyncEngine, clock: FakeClock, verifier_double: FakeTokenVerifier
) -> None:
    limiter = PostgresRateLimiter(clock)
    app = create_app(
        make_settings(),
        engine=engine,
        token_verifier=verifier_double,
        rate_limiter=limiter,
        clock=clock,
    )
    assert app.state.token_verifier is verifier_double
    assert app.state.rate_limiter is limiter
    assert app.state.clock is clock


async def test_m1_test_routes_are_not_in_the_openapi_snapshot() -> None:
    app = create_app(make_settings())
    paths = app.openapi()["paths"]
    assert not [p for p in paths if p.startswith("/_t")]
    await app.state.engine.dispose()
