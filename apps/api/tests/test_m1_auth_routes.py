"""M1-02b: session exchange, conversion, me, logout, revoke-all (AUTH-01..34).

The real ``create_app`` with the real Firebase verifier in emulator mode (unsigned tokens from
``mint_emulator_token``), the real session service and PostgreSQL. Persistence is always asserted
by a fresh ``/v1/auth/me`` call with the returned cookie.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from http.cookiejar import DefaultCookiePolicy
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_api.app import create_app
from knowserve_api.auth.deps import require_csrf
from knowserve_core import demo_cleanup
from knowserve_core.clock import FakeClock
from knowserve_core.firebase_tokens import FakeTokenVerifier, VerifierUnavailable
from knowserve_core.firebase_verifier import EMULATOR_ENV_VAR
from knowserve_core.ratelimit_pg import PostgresRateLimiter
from knowserve_core.settings import Settings
from knowserve_core.testing import DEFAULT_PROJECT_ID, mint_emulator_token
from knowserve_core.users_admin import disable_user

pytestmark = [pytest.mark.m1, pytest.mark.api, pytest.mark.integration]

ORIGIN = "http://localhost:5173"
COOKIE = "ks_session"
GENERIC = {"code": "UNAUTHENTICATED", "message": "Authentication required"}


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
    """Starts at the real now: emulator tokens carry real timestamps (overrides the root clock)."""
    return FakeClock(datetime.now(UTC))


def make_settings() -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql+asyncpg://u:p@localhost/db",
        "firebase_project_id": DEFAULT_PROJECT_ID,
        "firebase_auth_emulator_host": "localhost:9099",
        "api_allowed_origins": [ORIGIN],
    }
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def build_app(engine: AsyncEngine, clock: FakeClock, verifier: Any = None) -> FastAPI:
    return create_app(
        make_settings(),
        engine=engine,
        token_verifier=verifier,
        rate_limiter=PostgresRateLimiter(clock),
        clock=clock,
    )


@pytest_asyncio.fixture
async def app(engine: AsyncEngine, clock: FakeClock) -> FastAPI:
    return build_app(engine, clock)


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        # Tests send cookies explicitly; a jar would hide rotation and revocation behaviour.
        c.cookies.jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))
        yield c


def tok(
    uid: str,
    email: str | None = "user@example.test",
    *,
    verified: bool = True,
    provider: str = "password",
    auth_age: timedelta = timedelta(0),
    **kwargs: Any,
) -> str:
    now = datetime.now(UTC)
    return mint_emulator_token(
        uid,
        email=email,
        email_verified=verified,
        provider=provider,
        issued_at=now,
        auth_time=now - auth_age,
        **kwargs,
    )


def cookie_header(token: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE}={token}"}


def code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


async def exchange(client: httpx.AsyncClient, id_token: str, **headers: str) -> httpx.Response:
    return await client.post(
        "/v1/auth/session", json={"id_token": id_token}, headers={"Origin": ORIGIN, **headers}
    )


async def me(client: httpx.AsyncClient, cookie: str) -> httpx.Response:
    return await client.get("/v1/auth/me", headers=cookie_header(cookie))


def session_cookie(response: httpx.Response) -> str:
    value = response.cookies.get(COOKIE)
    assert value, "no session cookie in the response"
    return value


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with AsyncSession(engine) as db:
        return list((await db.execute(text(sql), params)).all())


# --- AUTH-01 / AUTH-06 / AUTH-08 / AUTH-09 -----------------------------------------------------


async def test_auth_01_first_exchange_creates_registered_user_and_persisted_session(
    client: httpx.AsyncClient, engine: AsyncEngine, clock: FakeClock
) -> None:
    response = await exchange(client, tok("uid-new", "  Alice@Example.TEST ", name="Alice"))
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "registered"
    assert body["email"] == "alice@example.test"
    assert body["display_name"] == "Alice"
    assert body["sign_in_provider"] == "password"
    assert body["active_department"] is None
    assert body["csrf_token"]
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(hours=24)

    users = await rows(engine, "SELECT kind, email, firebase_uid FROM users")
    assert [tuple(u) for u in users] == [("registered", "alice@example.test", "uid-new")]
    columns = await rows(
        engine,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'",
    )
    assert not [c for (c,) in columns if "password" in c]

    fresh = await me(client, session_cookie(response))  # persisted: a fresh request sees it
    assert fresh.status_code == 200
    assert fresh.json()["user_id"] == body["user_id"]
    assert fresh.json()["csrf_token"] == body["csrf_token"]


async def test_auth_01_google_provider_and_repeat_exchange_reuse_the_user(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    first = await exchange(client, tok("uid-g", "g@example.test", provider="google.com"))
    second = await exchange(client, tok("uid-g", "g@example.test", provider="google.com"))
    assert first.status_code == second.status_code == 200
    assert first.json()["user_id"] == second.json()["user_id"]
    assert first.json()["sign_in_provider"] == "google.com"
    assert len(await rows(engine, "SELECT 1 FROM users")) == 1
    assert len(await rows(engine, "SELECT 1 FROM sessions")) == 2


async def test_auth_06_session_cookie_attributes_and_hash_only_storage(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await exchange(client, tok("uid-c"))
    header = response.headers["set-cookie"].lower()
    for attribute in ("secure", "httponly", "samesite=lax", "path=/", "max-age=86400"):
        assert attribute in header
    assert "domain" not in header
    cookie = session_cookie(response)
    stored = await rows(engine, "SELECT token_hash FROM sessions")
    assert len(stored) == 1 and stored[0][0] != cookie and cookie not in stored[0][0]


async def test_auth_06_login_with_an_existing_cookie_rotates_the_session(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    first = await exchange(client, tok("uid-r"))
    old_cookie = session_cookie(first)
    second = await exchange(client, tok("uid-r"), **cookie_header(old_cookie))
    new_cookie = session_cookie(second)
    assert new_cookie != old_cookie
    assert (await me(client, old_cookie)).status_code == 401
    assert (await me(client, new_cookie)).status_code == 200
    assert second.json()["csrf_token"] != first.json()["csrf_token"]


async def test_auth_08_09_me_requires_a_session_and_returns_department_and_csrf(
    client: httpx.AsyncClient, make_user, make_session, session_factory
) -> None:
    assert (await client.get("/v1/auth/me")).status_code == 401
    async with session_factory() as db:
        dept = (await db.execute(text("SELECT id, slug, name FROM departments LIMIT 1"))).one()
    user = await make_user("registered", department_id=dept.id)
    handle = await make_session(user, department_id=dept.id)
    response = await me(client, handle.cookie)
    body = response.json()
    assert response.status_code == 200
    assert body["active_department"] == {"id": str(dept.id), "slug": dept.slug, "name": dept.name}
    assert body["csrf_token"] == handle.csrf_token
    assert body["kind"] == "registered"


async def test_auth_09_session_exchange_returns_the_last_active_department(
    client: httpx.AsyncClient, make_user, session_factory
) -> None:
    async with session_factory() as db:
        dept = (await db.execute(text("SELECT id FROM departments LIMIT 1"))).one()
    await make_user("registered", uid="uid-d", email="d@example.test", department_id=dept.id)
    response = await exchange(client, tok("uid-d", "d@example.test"))
    assert response.json()["active_department"]["id"] == str(dept.id)
    fresh = await me(client, session_cookie(response))
    assert fresh.json()["active_department"]["id"] == str(dept.id)


# --- AUTH-04 -----------------------------------------------------------------------------------


async def test_auth_04_admin_email_on_another_uid_is_refused_and_creates_nothing(
    client: httpx.AsyncClient, engine: AsyncEngine, make_user
) -> None:
    await make_user("admin", uid="uid-admin", email="admin@example.test")
    response = await exchange(client, tok("uid-impostor", "Admin@Example.test"))
    assert response.status_code == 401 and code(response) == "UNAUTHENTICATED"
    assert COOKIE not in response.cookies
    assert len(await rows(engine, "SELECT 1 FROM users")) == 1
    assert len(await rows(engine, "SELECT 1 FROM sessions")) == 0


async def test_auth_04_google_session_for_the_provisioned_admin_uid_is_admin(
    client: httpx.AsyncClient, make_user
) -> None:
    await make_user("admin", uid="uid-admin", email="admin@example.test")
    response = await exchange(client, tok("uid-admin", "admin@example.test", provider="google.com"))
    assert response.status_code == 200
    assert response.json()["kind"] == "admin"
    password = await exchange(client, tok("uid-admin", "admin@example.test"))
    assert password.json()["kind"] == "admin"
    assert (await me(client, session_cookie(response))).json()["kind"] == "admin"


async def test_auth_04_no_role_comes_from_email_provider_or_request_fields(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await client.post(
        "/v1/auth/session",
        json={"id_token": tok("admin", "admin@example.test"), "role": "admin", "kind": "admin"},
        headers={"Origin": ORIGIN, "X-Admin": "true"},
    )
    assert response.status_code == 200 and response.json()["kind"] == "registered"
    google = await exchange(client, tok("uid-x", "boss@example.test", provider="google.com"))
    assert google.json()["kind"] == "registered"
    kinds = await rows(engine, "SELECT DISTINCT kind FROM users")
    assert [k for (k,) in kinds] == ["registered"]


# --- AUTH-07 / AUTH-13 / AUTH-30 ---------------------------------------------------------------


async def test_auth_07_all_invalid_tokens_give_the_same_generic_401(
    client: httpx.AsyncClient,
) -> None:
    now = datetime.now(UTC)
    bad = {
        "garbage": "x" * 40,
        "wrong_project": tok("u", project_id="other-project"),
        "expired": mint_emulator_token(
            "u",
            email="u@example.test",
            email_verified=True,
            issued_at=now - timedelta(hours=3),
            lifetime=timedelta(hours=1),
        ),
        "anonymous": tok("u", None, provider="anonymous"),
        "anonymous_with_email": tok("u", "u@example.test", provider="anonymous"),
        "other_provider": tok("u", "u@example.test", provider="github.com"),
    }
    bodies = []
    for name, token in bad.items():
        response = await exchange(client, token)
        assert response.status_code == 401, name
        assert COOKIE not in response.cookies, name
        error = response.json()["error"]
        bodies.append({"code": error["code"], "message": error["message"]})
    assert all(b == GENERIC for b in bodies)


async def test_auth_13_unverified_email_gets_403_and_no_session_then_verified_succeeds(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    refused = await exchange(client, tok("uid-v", "v@example.test", verified=False))
    assert refused.status_code == 403 and code(refused) == "EMAIL_NOT_VERIFIED"
    assert COOKIE not in refused.cookies
    assert len(await rows(engine, "SELECT 1 FROM users")) == 0
    assert len(await rows(engine, "SELECT 1 FROM sessions")) == 0
    ok = await exchange(client, tok("uid-v", "v@example.test", verified=True))
    assert ok.status_code == 200
    assert (await me(client, session_cookie(ok))).status_code == 200


async def test_auth_13_stale_sign_in_needs_reauth_then_fresh_token_succeeds(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    stale = await exchange(client, tok("uid-s", auth_age=timedelta(minutes=10)))
    assert stale.status_code == 401 and code(stale) == "REAUTH_REQUIRED"
    assert COOKIE not in stale.cookies
    fresh = await exchange(client, tok("uid-s"))
    assert fresh.status_code == 200
    body = fresh.json()
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(hours=24)


async def test_auth_30_origin_is_checked_and_verifier_outage_fails_closed(
    engine: AsyncEngine, clock: FakeClock, client: httpx.AsyncClient
) -> None:
    for headers in ({}, {"Origin": "https://evil.example"}):
        response = await client.post(
            "/v1/auth/session", json={"id_token": tok("u")}, headers=headers
        )
        assert (response.status_code, code(response)) == (403, "ORIGIN_INVALID")

    fake = FakeTokenVerifier()
    fake.add("t" * 30, VerifierUnavailable())
    app = build_app(engine, clock, fake)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as c:
        down = await exchange(c, "t" * 30)
    assert (down.status_code, code(down)) == (503, "DEPENDENCY_UNAVAILABLE")


async def test_auth_30_disabled_user_cannot_get_a_new_session(
    client: httpx.AsyncClient, engine: AsyncEngine, session_factory, clock: FakeClock
) -> None:
    first = await exchange(client, tok("uid-z", "z@example.test"))
    user_id = uuid.UUID(first.json()["user_id"])
    async with session_factory() as db:
        assert await disable_user(db, user_id, clock=clock) is True
    again = await exchange(client, tok("uid-z", "z@example.test"))
    assert again.status_code == 401 and code(again) == "UNAUTHENTICATED"
    assert COOKIE not in again.cookies


# --- AUTH-21 -----------------------------------------------------------------------------------


async def test_auth_21_audit_entries_exist_and_hold_no_secrets(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    id_token = tok("uid-a", "a@example.test")
    ok = await exchange(client, id_token)
    cookie = session_cookie(ok)
    await exchange(client, tok("uid-other", "a@example.test"))  # email collision -> denied
    await exchange(client, tok("uid-u", "u@example.test", verified=False))  # unverified -> denied
    events = await rows(
        engine, "SELECT event, details::text FROM audit_events ORDER BY occurred_at"
    )
    names = [e for e, _ in events]
    assert "auth.session.created" in names
    denied = [d for e, d in events if e == "auth.session.denied"]
    assert len(denied) == 2
    assert any("email_in_use" in d for d in denied)
    assert any("email_not_verified" in d for d in denied)
    dump = " ".join(f"{e} {d}" for e, d in events)
    for secret in (id_token, cookie, ok.json()["csrf_token"]):
        assert secret not in dump


# --- AUTH-32 -----------------------------------------------------------------------------------


async def test_auth_32_second_uid_with_a_used_email_is_refused_audited_never_merged(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    first = await exchange(client, tok("uid-1", "shared@example.test"))
    second = await exchange(client, tok("uid-2", "SHARED@example.test", provider="google.com"))
    assert first.status_code == 200
    assert second.status_code == 401 and code(second) == "UNAUTHENTICATED"
    assert COOKIE not in second.cookies
    users = await rows(engine, "SELECT firebase_uid FROM users")
    assert [u for (u,) in users] == ["uid-1"]
    audit = await rows(
        engine, "SELECT details->>'reason' FROM audit_events WHERE event = 'auth.session.denied'"
    )
    assert [r for (r,) in audit] == ["email_in_use"]


async def test_auth_32_unverified_account_is_never_trusted_or_linked(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    await exchange(client, tok("uid-1", "mail@example.test"))
    unverified = await exchange(client, tok("uid-2", "mail@example.test", verified=False))
    assert unverified.status_code == 403
    assert len(await rows(engine, "SELECT 1 FROM users")) == 1


# --- AUTH-33 -----------------------------------------------------------------------------------


async def test_auth_33_logout_revokes_the_session_and_clears_the_cookie(
    client: httpx.AsyncClient,
) -> None:
    login = await exchange(client, tok("uid-l"))
    cookie, csrf = session_cookie(login), login.json()["csrf_token"]
    no_csrf = await client.post(
        "/v1/auth/logout", headers={**cookie_header(cookie), "Origin": ORIGIN}
    )
    assert (no_csrf.status_code, code(no_csrf)) == (403, "CSRF_INVALID")
    out = await client.post(
        "/v1/auth/logout",
        headers={**cookie_header(cookie), "Origin": ORIGIN, "X-CSRF-Token": csrf},
    )
    assert out.status_code == 204 and out.content == b""
    assert "max-age=0" in out.headers["set-cookie"].lower()
    assert (await me(client, cookie)).status_code == 401


async def test_auth_33_revoke_all_signs_out_every_session_and_needs_csrf(
    client: httpx.AsyncClient, make_user, make_session
) -> None:
    user = await make_user("registered")
    first, second = await make_session(user), await make_session(user)
    other = await make_session(await make_user("registered"))
    missing = await client.post(
        "/v1/auth/sessions/revoke-all", headers={**cookie_header(first.cookie), "Origin": ORIGIN}
    )
    assert (missing.status_code, code(missing)) == (403, "CSRF_INVALID")
    ok = await client.post(
        "/v1/auth/sessions/revoke-all",
        headers={**cookie_header(first.cookie), **first.headers},
    )
    assert ok.status_code == 200 and ok.json() == {"revoked": 2}
    assert (await me(client, first.cookie)).status_code == 401
    assert (await me(client, second.cookie)).status_code == 401
    assert (await me(client, other.cookie)).status_code == 200  # another user is untouched


async def test_auth_33_disable_user_revokes_sessions_and_audits(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    make_user,
    make_session,
    clock: FakeClock,
) -> None:
    user = await make_user("registered")
    one, two = await make_session(user), await make_session(user)
    async with session_factory() as db:
        assert await disable_user(db, user.id, clock=clock) is True
    async with session_factory() as db:
        assert await disable_user(db, user.id, clock=clock) is False  # already disabled
        assert await disable_user(db, uuid.uuid4(), clock=clock) is False  # unknown
    assert (await me(client, one.cookie)).status_code == 401
    assert (await me(client, two.cookie)).status_code == 401
    audit = await rows(engine, "SELECT 1 FROM audit_events WHERE event = 'auth.user.disabled'")
    assert len(audit) == 1
    disabled = await rows(engine, "SELECT disabled_at FROM users WHERE id = :id", id=user.id)
    assert disabled[0][0] is not None


async def test_auth_33_session_expires_24_hours_after_the_exchange(
    client: httpx.AsyncClient, clock: FakeClock
) -> None:
    cookie = session_cookie(await exchange(client, tok("uid-e")))
    clock.advance(hours=23, minutes=59, seconds=59)
    assert (await me(client, cookie)).status_code == 200
    clock.advance(seconds=1)
    expired = await me(client, cookie)
    assert expired.status_code == 401 and code(expired) == "UNAUTHENTICATED"


# --- AUTH-34 -----------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fixture_table(engine: AsyncEngine) -> AsyncIterator[None]:
    """Stand-in for future conversations/messages: rows that reference users.id per department."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE fx_dependent (id serial PRIMARY KEY, "
                "user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "department_id uuid NOT NULL, note text NOT NULL)"
            )
        )
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS fx_dependent"))


@pytest_asyncio.fixture
async def demo(make_user, make_session, session_factory, engine: AsyncEngine, fixture_table):
    """A Demo user with an anonymous session and dependent rows in two departments."""
    async with session_factory() as db:
        depts = [r[0] for r in (await db.execute(text("SELECT id FROM departments LIMIT 2"))).all()]
    user = await make_user("demo", uid="uid-demo", email=None, department_id=depts[0])
    handle = await make_session(
        user, provider="anonymous", ttl=timedelta(hours=1), department_id=depts[0]
    )
    async with engine.begin() as conn:
        for dept, note in zip(depts, ("first", "second"), strict=True):
            await conn.execute(
                text("INSERT INTO fx_dependent (user_id, department_id, note) VALUES (:u, :d, :n)"),
                {"u": user.id, "d": dept, "n": note},
            )
    return user, handle, depts


def convert(client: httpx.AsyncClient, handle, id_token: str) -> Any:
    return client.post(
        "/v1/auth/convert",
        json={"id_token": id_token},
        headers={**cookie_header(handle.cookie), **handle.headers},
    )


async def test_auth_34_convert_keeps_identity_and_records_and_issues_a_new_24h_session(
    client: httpx.AsyncClient, engine: AsyncEngine, demo, clock: FakeClock
) -> None:
    user, handle, depts = demo
    before = (await rows(engine, "SELECT created_at FROM users WHERE id = :id", id=user.id))[0][0]
    assert (await me(client, handle.cookie)).json()["kind"] == "demo"

    # The link happened in the browser; the sign-in is older than 5 minutes but the token is new.
    response = await convert(
        client, handle, tok("uid-demo", "New@Example.test", auth_age=timedelta(hours=2))
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "registered" and body["email"] == "new@example.test"
    assert body["user_id"] == str(user.id)
    assert body["active_department"]["id"] == str(depts[0])
    assert datetime.fromisoformat(body["expires_at"]) == clock.now() + timedelta(hours=24)
    new_cookie = session_cookie(response)
    assert new_cookie != handle.cookie and body["csrf_token"] != handle.csrf_token

    row = (
        await rows(
            engine,
            "SELECT id, firebase_uid, kind, created_at, converted_at, last_active_department_id "
            "FROM users",
        )
    )[0]
    assert (row.id, row.firebase_uid, row.kind) == (user.id, "uid-demo", "registered")
    assert row.created_at == before and row.converted_at == clock.now()
    assert row.last_active_department_id == depts[0]
    kept = await rows(engine, "SELECT department_id, note FROM fx_dependent ORDER BY note")
    assert {(d, n) for d, n in kept} == {(depts[0], "first"), (depts[1], "second")}

    assert (await me(client, handle.cookie)).status_code == 401  # old Demo session revoked
    fresh = await me(client, new_cookie)
    assert fresh.status_code == 200 and fresh.json()["kind"] == "registered"
    audit = await rows(engine, "SELECT 1 FROM audit_events WHERE event = 'auth.account.converted'")
    assert len(audit) == 1


async def test_auth_34_convert_grants_no_admin_or_new_permission(
    client: httpx.AsyncClient, demo, make_user
) -> None:
    await make_user("admin", uid="uid-admin", email="admin@example.test")
    user, handle, _ = demo
    clash = await convert(client, handle, tok("uid-demo", "admin@example.test"))
    assert clash.status_code == 409
    ok = await convert(client, handle, tok("uid-demo", "me@example.test"))
    new_cookie = session_cookie(ok)
    ping = await client.get("/v1/admin/ping", headers=cookie_header(new_cookie))
    assert ping.status_code in (403, 501)  # never 200: no Admin from a conversion


async def test_auth_34_repeat_is_safe(client: httpx.AsyncClient, engine: AsyncEngine, demo) -> None:
    user, handle, _ = demo
    first = await convert(client, handle, tok("uid-demo", "r@example.test"))
    assert first.status_code == 200
    # The revoked Demo cookie cannot repeat the call.
    again = await convert(client, handle, tok("uid-demo", "r@example.test"))
    assert again.status_code == 401
    # With the new Registered session the repeat is a 409 and changes nothing.
    new = first.json()
    registered = await client.post(
        "/v1/auth/convert",
        json={"id_token": tok("uid-demo", "r@example.test")},
        headers={
            **cookie_header(session_cookie(first)),
            "Origin": ORIGIN,
            "X-CSRF-Token": new["csrf_token"],
        },
    )
    assert (registered.status_code, code(registered)) == (409, "CONFLICT")
    assert len(await rows(engine, "SELECT 1 FROM users")) == 1
    assert (
        len(await rows(engine, "SELECT 1 FROM audit_events WHERE event = 'auth.account.converted'"))
        == 1
    )


async def test_auth_34_concurrent_converts_end_in_one_registered_user(
    client: httpx.AsyncClient, engine: AsyncEngine, demo
) -> None:
    _, handle, _ = demo
    results = await asyncio.gather(
        *(convert(client, handle, tok("uid-demo", "c@example.test")) for _ in range(3))
    )
    # A call that resolves its Demo session after the first commit sees it revoked (401); the
    # others find the row already registered with the same email and succeed. Never an error
    # state, never a second user.
    statuses = [r.status_code for r in results]
    assert set(statuses) <= {200, 401} and 200 in statuses
    rows_ = await rows(engine, "SELECT kind, email FROM users")
    assert [tuple(r) for r in rows_] == [("registered", "c@example.test")]
    converted = await rows(
        engine, "SELECT 1 FROM audit_events WHERE event = 'auth.account.converted'"
    )
    assert len(converted) == 1


async def test_auth_34_email_collision_is_409_no_merge_and_still_demo(
    client: httpx.AsyncClient, engine: AsyncEngine, demo, make_user
) -> None:
    owner = await make_user("registered", uid="uid-owner", email="taken@example.test")
    user, handle, _ = demo
    response = await convert(client, handle, tok("uid-demo", "Taken@Example.test"))
    assert (response.status_code, code(response)) == (409, "CONFLICT")
    assert COOKIE not in response.cookies
    kinds = await rows(engine, "SELECT id, kind FROM users ORDER BY firebase_uid")
    assert {(i, k) for i, k in kinds} == {(user.id, "demo"), (owner.id, "registered")}
    assert len(await rows(engine, "SELECT 1 FROM fx_dependent WHERE user_id = :u", u=user.id)) == 2
    assert (await me(client, handle.cookie)).json()["kind"] == "demo"  # still usable


async def test_auth_34_convert_rules(client: httpx.AsyncClient, demo, make_user, make_session):
    user, handle, _ = demo
    # Wrong uid, unverified, anonymous, bad CSRF, no session, registered session.
    wrong = await convert(client, handle, tok("someone-else", "x@example.test"))
    assert (wrong.status_code, code(wrong)) == (401, "UNAUTHENTICATED")
    unverified = await convert(client, handle, tok("uid-demo", "x@example.test", verified=False))
    assert (unverified.status_code, code(unverified)) == (403, "EMAIL_NOT_VERIFIED")
    anonymous = await convert(client, handle, tok("uid-demo", None, provider="anonymous"))
    assert anonymous.status_code == 401
    no_csrf = await client.post(
        "/v1/auth/convert",
        json={"id_token": tok("uid-demo")},
        headers={**cookie_header(handle.cookie), "Origin": ORIGIN},
    )
    assert (no_csrf.status_code, code(no_csrf)) == (403, "CSRF_INVALID")
    bare = await client.post(
        "/v1/auth/convert", json={"id_token": tok("uid-demo")}, headers={"Origin": ORIGIN}
    )
    assert bare.status_code == 401
    registered = await make_session(await make_user("registered"))
    conflict = await convert(client, registered, tok("uid-demo", "y@example.test"))
    assert (conflict.status_code, code(conflict)) == (409, "CONFLICT")
    assert (await me(client, handle.cookie)).json()["kind"] == "demo"  # nothing changed


async def test_auth_34_lost_call_is_completed_by_the_normal_exchange(
    client: httpx.AsyncClient, engine: AsyncEngine, demo
) -> None:
    user, handle, depts = demo
    # Firebase linking succeeded but /convert was never called; the user signs in again.
    response = await exchange(client, tok("uid-demo", "lost@example.test"))
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "registered" and body["user_id"] == str(user.id)
    assert body["active_department"]["id"] == str(depts[0])
    row = (await rows(engine, "SELECT kind, converted_at FROM users"))[0]
    assert row.kind == "registered" and row.converted_at is not None
    assert (await me(client, handle.cookie)).status_code == 401  # Demo session revoked
    assert len(await rows(engine, "SELECT 1 FROM fx_dependent WHERE user_id = :u", u=user.id)) == 2
    unverified = await exchange(client, tok("uid-demo", "lost@example.test", verified=False))
    assert unverified.status_code == 403  # a registered user stays registered


async def test_auth_34_unverified_exchange_leaves_the_demo_user_demo(
    client: httpx.AsyncClient, engine: AsyncEngine, demo
) -> None:
    response = await exchange(client, tok("uid-demo", "u@example.test", verified=False))
    assert response.status_code == 403
    assert (await rows(engine, "SELECT kind FROM users"))[0][0] == "demo"


async def test_auth_34_demo_email_of_the_admin_is_refused_at_exchange(
    client: httpx.AsyncClient, engine: AsyncEngine, demo, make_user
) -> None:
    await make_user("admin", uid="uid-admin", email="admin@example.test")
    response = await exchange(client, tok("uid-demo", "admin@example.test"))
    assert response.status_code == 401
    kinds = {k for (k,) in await rows(engine, "SELECT kind FROM users")}
    assert kinds == {"demo", "admin"}


async def test_auth_34_cleanup_first_means_convert_is_401_and_nothing_is_recreated(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    make_user,
    make_session,
    fixture_table,
) -> None:
    old = await make_user(
        "demo", uid="uid-old", email=None, created_at=clock.now() - timedelta(days=5)
    )
    handle = await make_session(old, provider="anonymous")
    result = await demo_cleanup.run(session_factory, make_settings(), clock)
    assert result.deleted_users == 1
    # The session went with the user (cascade), so the cookie is dead; /convert answers 401.
    response = await convert(client, handle, tok("uid-old", "late@example.test"))
    assert response.status_code == 401
    assert len(await rows(engine, "SELECT 1 FROM users")) == 0


async def test_auth_34_convert_first_means_cleanup_keeps_the_user(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    clock: FakeClock,
    make_user,
    make_session,
    fixture_table,
) -> None:
    old = await make_user(
        "demo", uid="uid-old", email=None, created_at=clock.now() - timedelta(days=5)
    )
    handle = await make_session(old, provider="anonymous")
    assert (await convert(client, handle, tok("uid-old", "won@example.test"))).status_code == 200
    result = await demo_cleanup.run(session_factory, make_settings(), clock)
    assert result.deleted_users == 0
    assert (await rows(engine, "SELECT kind FROM users"))[0][0] == "registered"


async def test_auth_34_locked_row_is_the_convert_guard_when_cleanup_deleted_it(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    clock: FakeClock,
    make_user,
    make_session,
    fixture_table,
) -> None:
    """The user disappears between the session lookup and the lock: 401, never recreated."""
    user = await make_user("demo", uid="uid-gone", email=None)
    handle = await make_session(user, provider="anonymous")
    async with engine.connect() as conn:
        trans = await conn.begin()
        await conn.execute(text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user.id})
        task = asyncio.create_task(convert(client, handle, tok("uid-gone", "g@example.test")))
        await asyncio.sleep(0.5)  # the request now waits on the row lock
        assert not task.done()
        await conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
        await trans.commit()
    response = await task
    assert response.status_code == 401
    assert len(await rows(engine, "SELECT 1 FROM users")) == 0


# --- guard for future routes -------------------------------------------------------------------


def _dependency_calls(dependant: Any) -> Iterator[Any]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from _dependency_calls(sub)


def _api_routes(routes: Any) -> Iterator[Any]:
    """Flatten routers included lazily by FastAPI (``include_router`` wraps them)."""
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _api_routes(nested.routes)
        else:
            yield route


async def test_auth_14_every_unsafe_route_requires_csrf_except_the_session_creators(
    app: FastAPI,
) -> None:
    exempt = {"/v1/auth/session", "/v1/demo/start"}
    pending_stub: set[str] = set()  # M1-04 landed; the real route is guarded below
    checked = 0
    for route in _api_routes(app.routes):
        if not isinstance(route, APIRoute):
            continue
        unsafe = (route.methods or set()) - {"GET", "HEAD", "OPTIONS"}
        if not unsafe or route.path in exempt or route.path in pending_stub:
            continue
        if route.path.startswith("/v1/spike") or route.path.startswith("/v1/operator"):
            continue
        checked += 1
        assert require_csrf in set(_dependency_calls(route.dependant)), (
            f"{sorted(unsafe)} {route.path} lacks require_csrf"
        )
    assert checked >= 3  # logout, convert, revoke-all at minimum
