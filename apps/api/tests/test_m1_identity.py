"""M1-04 / M1-05: Try Demo, departments, Admin guard, Admin provisioning, log redaction.

Real verifier path: the app is built with the Firebase emulator host and project ``demo-knowserve``
and the tests mint unsigned emulator tokens. Test-only routes (``/_t``) are added to the test app,
never to ``create_app`` or the OpenAPI snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.admin_seed import ProvisioningError, provision_admin
from knowserve_api.app import create_app
from knowserve_api.auth.deps import get_db, require_active_department, require_admin
from knowserve_core.clock import FakeClock
from knowserve_core.firebase_verifier import EMULATOR_ENV_VAR
from knowserve_core.identity import Identity
from knowserve_core.models import AuditEvent, Department, Session, User
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEFAULT_PROJECT_ID, mint_emulator_token

pytestmark = [pytest.mark.m1, pytest.mark.api, pytest.mark.integration]

ORIGIN = "http://localhost:5173"
COOKIE = "ks_session"
PROXY_SECRET = "proxy-secret-for-tests-only"


@pytest.fixture
def clock() -> FakeClock:
    # Real "now": the SDK path in emulator mode still looks at wall-clock token claims.
    return FakeClock(datetime.now(UTC).replace(microsecond=0))


@pytest.fixture(autouse=True)
def _restore_emulator_env() -> Iterator[None]:
    saved = os.environ.get(EMULATOR_ENV_VAR)
    yield
    if saved is None:
        os.environ.pop(EMULATOR_ENV_VAR, None)
    else:
        os.environ[EMULATOR_ENV_VAR] = saved


# --- test-only routes (TEST app only) ----------------------------------------------------------

test_router = APIRouter(prefix="/_t")


@test_router.get("/dept")
async def t_dept(identity: Annotated[Identity, Depends(require_active_department)]) -> dict:
    return {"department": str(identity.active_department_id), "user": str(identity.user_id)}


@test_router.get("/scope")
async def t_scope(
    identity: Annotated[Identity, Depends(require_active_department)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Stand-in for a department-scoped query: the scope is the active department only,
    whatever the kind (SEC-03/17). Real document queries arrive in M2."""
    stmt = select(Department.slug).where(Department.id == identity.active_department_id)
    return {"kind": identity.kind, "slugs": list((await db.scalars(stmt)).all())}


@test_router.get("/admin")
async def t_admin(identity: Annotated[Identity, Depends(require_admin)]) -> dict:
    return {"kind": identity.kind}


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_project_id": DEFAULT_PROJECT_ID,
        "firebase_auth_emulator_host": "localhost:9099",
        "api_allowed_origins": [ORIGIN],
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def build_app(engine: AsyncEngine, clock: FakeClock, **settings: Any) -> FastAPI:
    app = create_app(
        make_settings(**settings),
        engine=engine,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
    )  # real FirebaseTokenVerifier (emulator mode)
    app.include_router(test_router)
    return app


def http(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")


@pytest_asyncio.fixture
async def client(engine: AsyncEngine, clock: FakeClock) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(engine, clock)
    async with http(app) as c:
        yield c
    app.state.token_verifier.close()


def anon_token(clock: FakeClock, uid: str = "anon-1", **kwargs: Any) -> str:
    kwargs.setdefault("provider", "anonymous")
    kwargs.setdefault("issued_at", clock.now())
    return mint_emulator_token(uid, **kwargs)


async def start(
    client: httpx.AsyncClient, token: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    response = await client.post(
        "/v1/demo/start", json={"id_token": token}, headers={"Origin": ORIGIN, **(headers or {})}
    )
    client.cookies.clear()  # tests pass cookies explicitly; never rely on the jar
    return response


def openapi_paths(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    app: FastAPI = client._transport.app  # type: ignore[attr-defined]
    return app.openapi()["paths"]


def code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


def cookie_of(response: httpx.Response) -> dict[str, str]:
    value = response.cookies.get(COOKIE)
    assert value
    return {"Cookie": f"{COOKIE}={value}"}


def mutate_headers(response: httpx.Response) -> dict[str, str]:
    return {**cookie_of(response), "Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


async def departments(client: httpx.AsyncClient, headers: dict[str, str]) -> list[dict]:
    return (await client.get("/v1/departments", headers=headers)).json()["departments"]


async def select_department(
    client: httpx.AsyncClient, headers: dict[str, str], department_id: str
) -> httpx.Response:
    return await client.put(
        "/v1/session/department", json={"department_id": department_id}, headers=headers
    )


def handle_headers(handle: Any) -> dict[str, str]:
    return {"Cookie": f"{COOKIE}={handle.cookie}", **handle.headers}


# --- AUTH-16: Try Demo -------------------------------------------------------------------------


async def test_auth_16_demo_start_creates_identity_and_session(
    client: httpx.AsyncClient, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await start(client, anon_token(clock, "anon-a"))
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "demo" and body["sign_in_provider"] == "anonymous"
    assert body["email"] is None and body["active_department"] is None
    assert body["csrf_token"]
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(hours=24)
    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "Secure" in set_cookie and "SameSite=lax" in set_cookie
    assert "Domain" not in set_cookie
    async with session_factory() as db:
        user = await db.scalar(select(User).where(User.firebase_uid == "anon-a"))
        assert user is not None and user.kind == "demo" and user.email is None
        assert await db.scalar(select(func.count()).select_from(Session)) == 1
    listed = await client.get("/v1/departments", headers=cookie_of(response))
    assert listed.status_code == 200


async def test_auth_16_demo_start_needs_allowed_origin(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    response = await client.post(
        "/v1/demo/start",
        json={"id_token": anon_token(clock)},
        headers={"Origin": "https://evil.test"},
    )
    assert (response.status_code, code(response)) == (403, "ORIGIN_INVALID")


async def test_auth_16_non_anonymous_token_is_refused_with_generic_401(
    client: httpx.AsyncClient, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    for provider, email in (("password", "p@example.test"), ("google.com", "g@example.test")):
        token = anon_token(clock, f"uid-{provider}", provider=provider, email=email)
        response = await start(client, token)
        assert (response.status_code, code(response)) == (401, "UNAUTHENTICATED"), provider
    forged = await start(client, anon_token(clock, "x", project_id="other-project"))
    assert (forged.status_code, code(forged)) == (401, "UNAUTHENTICATED")
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0


async def test_auth_16_stale_sign_in_needs_reauth(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    token = anon_token(clock, auth_time=clock.now() - timedelta(hours=1))
    response = await start(client, token)
    assert (response.status_code, code(response)) == (401, "REAUTH_REQUIRED")


async def test_auth_16_two_demo_users_are_isolated(
    client: httpx.AsyncClient, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    a = await start(client, anon_token(clock, "anon-a"))
    b = await start(client, anon_token(clock, "anon-b"))
    assert a.json()["user_id"] != b.json()["user_id"]
    assert a.json()["csrf_token"] != b.json()["csrf_token"]
    depts = await departments(client, cookie_of(a))
    first, second = depts[0]["id"], depts[1]["id"]
    await select_department(client, mutate_headers(a), first)
    await select_department(client, mutate_headers(b), second)
    ra = await client.get("/_t/dept", headers=cookie_of(a))
    rb = await client.get("/_t/dept", headers=cookie_of(b))
    assert ra.json() == {"department": first, "user": a.json()["user_id"]}
    assert rb.json() == {"department": second, "user": b.json()["user_id"]}
    # A's CSRF token is useless on B's session.
    crossed = await client.put(
        "/v1/session/department",
        json={"department_id": first},
        headers={**cookie_of(b), "Origin": ORIGIN, "X-CSRF-Token": a.json()["csrf_token"]},
    )
    assert (crossed.status_code, code(crossed)) == (403, "CSRF_INVALID")
    async with session_factory() as db:
        rows = {u.firebase_uid: u.last_active_department_id for u in await db.scalars(select(User))}
    assert str(rows["anon-a"]) == first and str(rows["anon-b"]) == second


async def test_auth_16_demo_cannot_use_admin_routes(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    response = await start(client, anon_token(clock))
    for path in ("/v1/admin/ping", "/_t/admin"):
        forbidden = await client.get(path, headers=cookie_of(response))
        assert (forbidden.status_code, code(forbidden)) == (403, "FORBIDDEN")


async def test_auth_16_expired_demo_identity_gets_demo_expired(
    client: httpx.AsyncClient, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first = await start(client, anon_token(clock, "anon-old"))
    assert first.status_code == 200
    clock.advance(hours=23, minutes=59, seconds=58)
    within = await start(client, anon_token(clock, "anon-old"))
    assert within.status_code == 200
    # a session started late never outlives the identity's own 24 hours
    assert datetime.fromisoformat(within.json()["expires_at"]) == datetime.fromisoformat(
        first.json()["expires_at"]
    )
    clock.advance(seconds=2)
    expired = await start(client, anon_token(clock, "anon-old"))
    assert (expired.status_code, code(expired)) == (401, "DEMO_EXPIRED")
    assert "set-cookie" not in expired.headers
    # reuse never extends it, on any later attempt
    clock.advance(hours=30)
    again = await start(client, anon_token(clock, "anon-old"))
    assert (again.status_code, code(again)) == (401, "DEMO_EXPIRED")
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(Session)) == 2
    # a brand-new anonymous uid starts fine
    assert (await start(client, anon_token(clock, "anon-new"))).status_code == 200


async def test_auth_16_existing_non_demo_uid_gets_generic_401(
    client: httpx.AsyncClient, clock: FakeClock, make_user
) -> None:
    await make_user("registered", uid="uid-reg")
    await make_user("admin", uid="uid-adm")
    for uid in ("uid-reg", "uid-adm"):
        response = await start(client, anon_token(clock, uid))
        assert (response.status_code, code(response)) == (401, "UNAUTHENTICATED")
        assert "set-cookie" not in response.headers


async def test_auth_16_disabled_demo_identity_gets_generic_401(
    client: httpx.AsyncClient,
    clock: FakeClock,
    make_user,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user = await make_user("demo", uid="uid-dis")
    async with session_factory() as db:
        await db.execute(text("UPDATE users SET disabled_at = now() WHERE id = :i"), {"i": user.id})
        await db.commit()
    response = await start(client, anon_token(clock, "uid-dis"))
    assert (response.status_code, code(response)) == (401, "UNAUTHENTICATED")


# --- AUTH-15 / SEC-10: rate limit and client IP ------------------------------------------------


async def test_auth_15_sixth_start_from_one_ip_is_429_then_window_resets(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    for i in range(5):
        assert (await start(client, anon_token(clock, f"rl-{i}"))).status_code == 200
    sixth = await start(client, anon_token(clock, "rl-5"))
    assert (sixth.status_code, code(sixth)) == (429, "RATE_LIMITED")
    clock.advance(hours=1)  # new window
    assert (await start(client, anon_token(clock, "rl-6"))).status_code == 200


async def test_auth_15_limits_come_from_configuration(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = build_app(engine, clock, demo_start_limit=2, demo_start_window_seconds=60)
    async with http(app) as c:
        assert (await start(c, anon_token(clock, "c1"))).status_code == 200
        assert (await start(c, anon_token(clock, "c2"))).status_code == 200
        assert (await start(c, anon_token(clock, "c3"))).status_code == 429
        clock.advance(seconds=60)
        assert (await start(c, anon_token(clock, "c4"))).status_code == 200
    app.state.token_verifier.close()


async def test_sec_10_proxied_client_ip_is_used_and_forwarded_for_is_ignored(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = build_app(engine, clock, proxy_shared_secret=PROXY_SECRET)
    proxy = {"X-KS-Proxy-Secret": PROXY_SECRET}
    async with http(app) as c:
        for i in range(5):
            headers = {**proxy, "X-KS-Client-IP": "203.0.113.7", "X-Forwarded-For": f"9.9.9.{i}"}
            assert (await start(c, anon_token(clock, f"p{i}"), headers)).status_code == 200
        # same vouched IP: a spoofed X-Forwarded-For does not buy a fresh bucket
        sixth = await start(
            c,
            anon_token(clock, "p5"),
            {**proxy, "X-KS-Client-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4"},
        )
        assert (sixth.status_code, code(sixth)) == (429, "RATE_LIMITED")
        # a different vouched IP has its own bucket
        other = await start(c, anon_token(clock, "p6"), {**proxy, "X-KS-Client-IP": "203.0.113.8"})
        assert other.status_code == 200
        # without the proxy secret the guard rejects before any route code
        direct = await start(c, anon_token(clock, "p7"), {"X-KS-Client-IP": "198.51.100.1"})
        assert (direct.status_code, code(direct)) == (403, "DIRECT_ACCESS_DENIED")
    app.state.token_verifier.close()


async def test_sec_10_missing_proxied_ip_shares_one_conservative_bucket(
    engine: AsyncEngine, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    app = build_app(engine, clock, proxy_shared_secret=PROXY_SECRET, demo_start_limit=1)
    proxy = {"X-KS-Proxy-Secret": PROXY_SECRET}
    async with http(app) as c:
        assert (await start(c, anon_token(clock, "m1"), proxy)).status_code == 200
        second = await start(c, anon_token(clock, "m2"), {**proxy, "X-KS-Client-IP": "not-an-ip"})
        assert second.status_code == 429
    async with session_factory() as db:
        keys = set((await db.execute(text("SELECT key FROM rate_limit_counters"))).scalars())
    assert len(keys) == 1 and "unknown" not in next(iter(keys))  # one hashed shared bucket
    app.state.token_verifier.close()


# --- AUTH-17 / AUTH-20: departments ------------------------------------------------------------


async def test_auth_20_list_returns_the_five_seeded_departments_in_order(
    client: httpx.AsyncClient, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await start(client, anon_token(clock))
    listed = await departments(client, cookie_of(response))
    assert len(listed) == 5
    async with session_factory() as db:
        expected = [
            (str(d.id), d.slug)
            for d in await db.scalars(select(Department).order_by(Department.position))
        ]
    assert [(d["id"], d["slug"]) for d in listed] == expected
    assert all(set(d) == {"id", "slug", "name"} for d in listed)


async def test_auth_20_list_requires_a_session(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/departments")
    assert (response.status_code, code(response)) == (401, "UNAUTHENTICATED")


async def test_auth_20_no_create_update_or_delete_department_routes(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    paths = openapi_paths(client)
    dept_routes = {
        (method.upper(), path)
        for path, item in paths.items()
        if "department" in path
        for method in item
    }
    assert dept_routes == {("GET", "/v1/departments"), ("PUT", "/v1/session/department")}
    response = await start(client, anon_token(clock))
    headers = mutate_headers(response)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = await client.request(method, "/v1/departments", json={"name": "x"}, headers=headers)
        assert r.status_code == 405, method
        r = await client.request(
            method, f"/v1/departments/{uuid.uuid4()}", json={"name": "x"}, headers=headers
        )
        assert r.status_code == 404, method


async def test_auth_17_every_department_is_selectable_and_switchable(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    response = await start(client, anon_token(clock))
    headers = mutate_headers(response)
    for dept in await departments(client, headers):
        switched = await select_department(client, headers, dept["id"])
        assert switched.status_code == 200
        assert switched.json()["active_department"] == dept
        assert switched.json()["csrf_token"] == response.json()["csrf_token"]
        assert (await client.get("/_t/dept", headers=headers)).json()["department"] == dept["id"]


async def test_auth_17_unknown_department_is_rejected_and_nothing_changes(
    client: httpx.AsyncClient, clock: FakeClock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await start(client, anon_token(clock))
    headers = mutate_headers(response)
    first = (await departments(client, headers))[0]["id"]
    await select_department(client, headers, first)
    bad = await select_department(client, headers, str(uuid.uuid4()))
    assert (bad.status_code, code(bad)) == (422, "VALIDATION_ERROR")
    notuuid = await select_department(client, headers, "nope")
    assert notuuid.status_code == 422
    assert (await client.get("/_t/dept", headers=headers)).json()["department"] == first
    async with session_factory() as db:
        assert str(await db.scalar(select(User.last_active_department_id))) == first


async def test_auth_17_switch_requires_csrf_and_origin(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    response = await start(client, anon_token(clock))
    dept = (await departments(client, cookie_of(response)))[0]["id"]
    body = {"department_id": dept}
    no_csrf = await client.put(
        "/v1/session/department", json=body, headers={**cookie_of(response), "Origin": ORIGIN}
    )
    assert (no_csrf.status_code, code(no_csrf)) == (403, "CSRF_INVALID")
    bad_origin = await client.put(
        "/v1/session/department",
        json=body,
        headers={**mutate_headers(response), "Origin": "https://evil.test"},
    )
    assert (bad_origin.status_code, code(bad_origin)) == (403, "ORIGIN_INVALID")
    anon = await client.put("/v1/session/department", json=body, headers={"Origin": ORIGIN})
    assert (anon.status_code, code(anon)) == (401, "UNAUTHENTICATED")


async def test_auth_17_first_login_has_no_department_so_409(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    response = await start(client, anon_token(clock))
    assert response.json()["active_department"] is None
    blocked = await client.get("/_t/dept", headers=cookie_of(response))
    assert (blocked.status_code, code(blocked)) == (409, "ACTIVE_DEPARTMENT_REQUIRED")


async def test_auth_17_last_department_is_restored_on_a_new_session(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    first = await start(client, anon_token(clock, "anon-r"))
    dept = (await departments(client, cookie_of(first)))[3]
    await select_department(client, mutate_headers(first), dept["id"])
    second = await start(client, anon_token(clock, "anon-r"))
    assert second.json()["active_department"] == dept
    assert (await client.get("/_t/dept", headers=cookie_of(second))).status_code == 200
    # a different Demo identity does not inherit it
    other = await start(client, anon_token(clock, "anon-other"))
    assert other.json()["active_department"] is None


async def test_sec_16_selection_grants_nothing(client: httpx.AsyncClient, clock: FakeClock) -> None:
    demo = await start(client, anon_token(clock))
    headers = mutate_headers(demo)
    dept = (await departments(client, headers))[0]["id"]
    await client.put(
        "/v1/session/department",
        json={"department_id": dept, "role": "admin", "kind": "admin"},
        headers=headers,
    )
    ping = await client.get("/v1/admin/ping", headers=headers)
    assert (ping.status_code, code(ping)) == (403, "FORBIDDEN")
    scope = await client.get("/_t/scope", headers=headers)
    assert scope.json()["kind"] == "demo" and len(scope.json()["slugs"]) == 1


# --- AUTH-04 / AUTH-11 / SEC-03 / SEC-17: Admin guard ------------------------------------------


async def test_auth_11_admin_ping_matrix(
    client: httpx.AsyncClient, make_user, make_session
) -> None:
    assert (await client.get("/v1/admin/ping")).status_code == 401
    registered = await make_session(await make_user("registered"))
    demo = await make_session(await make_user("demo"), provider="anonymous")
    admin_pw = await make_session(await make_user("admin"), provider="password")
    admin_google = await make_session(await make_user("admin"), provider="google.com")
    for handle in (registered, demo):
        r = await client.get("/v1/admin/ping", headers=handle_headers(handle))
        assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    for handle in (admin_pw, admin_google):
        r = await client.get("/v1/admin/ping", headers=handle_headers(handle))
        assert (r.status_code, r.json()) == (200, {"status": "ok"})


async def test_auth_04_admin_comes_only_from_the_users_row(
    client: httpx.AsyncClient,
    make_user,
    make_session,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    admin = await make_user("admin", uid="uid-admin", email="boss@example.test")
    # another uid, an email that looks like the Admin's, a role in the payload: all non-admin
    lookalike = await make_user("registered", uid="uid-other", email="BOSS@example.test")
    handle = await make_session(lookalike, provider="google.com")
    headers = handle_headers(handle)
    assert (await client.get("/v1/admin/ping", headers=headers)).status_code == 403
    dept = (await departments(client, headers))[0]["id"]
    await client.put(
        "/v1/session/department", json={"department_id": dept, "role": "admin"}, headers=headers
    )
    assert (await client.get("/v1/admin/ping", headers=headers)).status_code == 403
    # the Admin's own session works whatever the provider; demotion takes effect at once
    ok = await make_session(admin, provider="password")
    assert (await client.get("/v1/admin/ping", headers=handle_headers(ok))).status_code == 200
    async with session_factory() as db:
        await db.execute(text("UPDATE users SET kind='registered' WHERE id=:i"), {"i": admin.id})
        await db.commit()
    assert (await client.get("/v1/admin/ping", headers=handle_headers(ok))).status_code == 403


async def test_auth_04_no_http_route_creates_or_elevates_an_admin(
    client: httpx.AsyncClient,
) -> None:
    paths = openapi_paths(client)
    assert not [p for p in paths if "role" in p or "promote" in p or "elevate" in p]
    # M3 adds the Admin document and import routes (docs/contracts/admin-api.md). None of them
    # manages users or roles; the full matrix is in test_m3_admin_contract.py.
    admin_paths = {p: sorted(m) for p, m in paths.items() if p.startswith("/v1/admin")}
    assert admin_paths["/v1/admin/ping"] == ["get"]
    assert not [p for p in admin_paths if "user" in p or "admin-" in p or "grant" in p]
    assert set(admin_paths) <= {
        "/v1/admin/ping",
        "/v1/admin/documents",
        "/v1/admin/documents/{document_id}",
        "/v1/admin/documents/{document_id}/access",
        "/v1/admin/documents/{document_id}/events",
        "/v1/admin/documents/{document_id}/replace",
        "/v1/admin/documents/{document_id}/retry",
        "/v1/admin/imports/confirm",
        "/v1/admin/imports/preview",
    }


async def test_sec_03_17_admin_has_no_bypass_active_department_scopes_the_admin(
    client: httpx.AsyncClient, make_user, make_session
) -> None:
    admin = await make_session(await make_user("admin"), provider="google.com")
    headers = handle_headers(admin)
    no_dept = await client.get("/_t/scope", headers=headers)
    assert (no_dept.status_code, code(no_dept)) == (409, "ACTIVE_DEPARTMENT_REQUIRED")
    chosen = (await departments(client, headers))[1]
    await select_department(client, headers, chosen["id"])
    scoped = await client.get("/_t/scope", headers=headers)
    assert scoped.json() == {"kind": "admin", "slugs": [chosen["slug"]]}


# M2 expectations for SEC-03/17 (documents do not exist yet). Each entry becomes a real test in M2
# and is removed from this list when it is implemented.
M2_ADMIN_NO_BYPASS_EXPECTATIONS = (
    "Admin with active department A lists only documents whose access rules allow A",
    "Admin requesting a document of department B by id gets 404 (not 403)",
    "Admin chat retrieval in department A never returns chunks of department B",
    "Admin download/preview of a document not visible to A is refused",
)


def test_sec_03_17_m2_expectations_are_recorded() -> None:
    assert len(M2_ADMIN_NO_BYPASS_EXPECTATIONS) == 4


# --- AUTH-04: provisioning command -------------------------------------------------------------


async def test_auth_04_provisioning_creates_then_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await provision_admin(
        session_factory, firebase_uid="uid-A", email="  Boss@Example.TEST "
    )
    second = await provision_admin(session_factory, firebase_uid="uid-A", email="boss@example.test")
    assert (first, second) == ("created", "unchanged")
    async with session_factory() as db:
        admins = (await db.scalars(select(User).where(User.kind == "admin"))).all()
        assert len(admins) == 1
        assert admins[0].firebase_uid == "uid-A" and admins[0].email == "boss@example.test"
        stmt = select(AuditEvent).where(AuditEvent.event == "admin.provisioned")
        events = (await db.scalars(stmt)).all()
        assert len(events) == 1  # the unchanged run writes nothing
        assert "uid-A" not in json.dumps(events[0].details)


async def test_auth_04_provisioning_promotes_an_existing_registered_uid(
    session_factory: async_sessionmaker[AsyncSession], make_user
) -> None:
    await make_user("registered", uid="uid-P", email="p@example.test")
    outcome = await provision_admin(session_factory, firebase_uid="uid-P", email="P@example.test")
    assert outcome == "promoted"
    async with session_factory() as db:
        user = await db.scalar(select(User).where(User.firebase_uid == "uid-P"))
        assert user is not None and user.kind == "admin"


async def test_auth_04_provisioning_refuses_a_second_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await provision_admin(session_factory, firebase_uid="uid-A", email="a@example.test")
    with pytest.raises(ProvisioningError):
        await provision_admin(session_factory, firebase_uid="uid-B", email="b@example.test")
    async with session_factory() as db:
        count = await db.scalar(select(func.count()).select_from(User).where(User.kind == "admin"))
        assert count == 1


async def test_auth_04_provisioning_refuses_conflicts_and_bad_input(
    session_factory: async_sessionmaker[AsyncSession], make_user
) -> None:
    await make_user("registered", uid="uid-C", email="c@example.test")
    await make_user("demo", uid="uid-D")
    with pytest.raises(ProvisioningError):  # the email belongs to another account
        await provision_admin(session_factory, firebase_uid="uid-B", email="c@example.test")
    with pytest.raises(ProvisioningError):  # a Demo identity is never promoted
        await provision_admin(session_factory, firebase_uid="uid-D", email="d@example.test")
    with pytest.raises(ProvisioningError):
        await provision_admin(session_factory, firebase_uid="", email="d@example.test")
    with pytest.raises(ProvisioningError):
        await provision_admin(session_factory, firebase_uid="uid-E", email="not-an-email")
    async with session_factory() as db:
        count = await db.scalar(select(func.count()).select_from(User).where(User.kind == "admin"))
        assert count == 0
        await db.execute(delete(AuditEvent))


async def test_auth_04_command_needs_only_database_and_admin_variables(
    migrated_database: str, session_factory: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KS_")}
    env.update(
        KS_DATABASE_URL=migrated_database,
        KS_ADMIN_FIREBASE_UID="uid-cmd-secretish",
        KS_ADMIN_EMAIL="Cmd@Example.test",
    )

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "knowserve_api.admin_seed"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    first = await asyncio.to_thread(run)
    second = await asyncio.to_thread(run)
    assert (first.returncode, second.returncode) == (0, 0), first.stderr + second.stderr
    assert "created" in first.stdout and "unchanged" in second.stdout
    for output in (first.stdout, first.stderr, second.stdout, second.stderr):
        assert "uid-cmd-secretish" not in output and "cmd@example.test" not in output.lower()
    async with session_factory() as db:
        count = await db.scalar(select(func.count()).select_from(User).where(User.kind == "admin"))
        assert count == 1
    env.pop("KS_ADMIN_EMAIL")
    missing = await asyncio.to_thread(run)
    assert missing.returncode == 2


# --- MON-05: no secrets in logs or audit events ------------------------------------------------


async def test_mon_05_flow_leaks_no_token_cookie_or_csrf_to_logs_or_audit(
    client: httpx.AsyncClient,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    caplog.set_level(logging.DEBUG)
    token = anon_token(clock, "anon-redact")
    response = await start(client, token)
    assert response.status_code == 200
    cookie = response.cookies.get(COOKIE)
    csrf = response.json()["csrf_token"]
    headers = mutate_headers(response)
    dept = (await departments(client, headers))[0]["id"]
    await select_department(client, headers, dept)
    # failures too: forged token, wrong CSRF, wrong provider
    bad = anon_token(clock, "anon-bad", project_id="other")
    await start(client, bad)
    await client.put(
        "/v1/session/department",
        json={"department_id": dept},
        headers={**cookie_of(response), "Origin": ORIGIN, "X-CSRF-Token": "wrong-csrf-value-123"},
    )
    await start(client, anon_token(clock, "pw", provider="password", email="e@example.test"))
    logged = caplog.text + "\n".join(r.getMessage() + repr(r.__dict__) for r in caplog.records)
    async with session_factory() as db:
        rows = (await db.execute(select(AuditEvent.event, AuditEvent.details, AuditEvent.ip))).all()
    audit_text = json.dumps([[r[0], r[1], r[2]] for r in rows], default=str)
    assert {"demo.started", "demo.denied", "department.selected"} <= {r[0] for r in rows}
    for secret in (token, bad, cookie, csrf, "wrong-csrf-value-123", token.split(".")[1]):
        assert secret
        assert secret not in logged
        assert secret not in audit_text
