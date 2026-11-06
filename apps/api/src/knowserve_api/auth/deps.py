"""Identity, CSRF/Origin and cookie helpers shared by every M1 route (M1-02a).

Contract: docs/contracts/auth-session.md. Typical use::

    @router.put("/v1/session/department")
    async def switch(identity: Annotated[Identity, Depends(require_csrf)], ...): ...

``get_identity`` is cached per request, so stacking ``require_csrf`` and ``require_admin`` costs one
session lookup. ``get_db`` yields a plain ``AsyncSession``; routes that write call ``commit()``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core.clock import Clock
from knowserve_core.firebase_tokens import TokenVerifier
from knowserve_core.identity import Identity
from knowserve_core.ratelimit import RateLimiter
from knowserve_core.security import tokens_equal
from knowserve_core.sessions import SessionService
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# --- state getters (set in create_app) ---------------------------------------------------------


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_token_verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_session_service(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> SessionService:
    return SessionService(settings.session_ttl_seconds, clock)


# --- identity ----------------------------------------------------------------------------------


def unauthenticated() -> AppError:
    return AppError(401, "UNAUTHENTICATED", "Authentication required")


async def get_identity(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> Identity:
    """The identity of the cookie's session, or 401 UNAUTHENTICATED (AUTH-10)."""
    token = request.cookies.get(settings.session_cookie_name)
    identity = await service.lookup_by_token(db, token) if token else None
    if identity is None:
        raise unauthenticated()
    return identity


async def require_registered(identity: Annotated[Identity, Depends(get_identity)]) -> Identity:
    """Registered or Admin accounts only; Demo identities get 403 FORBIDDEN."""
    if identity.kind not in ("registered", "admin"):
        raise AppError(403, "FORBIDDEN", "Forbidden")
    return identity


async def require_admin(identity: Annotated[Identity, Depends(get_identity)]) -> Identity:
    """Admin only. ``kind`` is read from ``users.kind`` for this session's user (AUTH-04)."""
    if identity.kind != "admin":
        raise AppError(403, "FORBIDDEN", "Forbidden")
    return identity


async def require_active_department(
    identity: Annotated[Identity, Depends(get_identity)],
) -> Identity:
    if identity.active_department_id is None:
        raise AppError(409, "ACTIVE_DEPARTMENT_REQUIRED", "Select a department first")
    return identity


# --- CSRF and Origin (AUTH-14) -----------------------------------------------------------------


def _normalize_origin(value: str) -> str:
    return value.strip().rstrip("/")


def check_origin(request: Request, settings: Settings) -> None:
    """The ``Origin`` header must be one of ``KS_API_ALLOWED_ORIGINS``."""
    origin = request.headers.get("origin")
    allowed = {_normalize_origin(item) for item in settings.api_allowed_origins}
    if not origin or origin not in allowed:
        raise AppError(403, "ORIGIN_INVALID", "Request origin is not allowed")


async def require_origin(
    request: Request, settings: Annotated[Settings, Depends(get_settings_dep)]
) -> None:
    """Origin-only check for the session-creating endpoints, which have no session yet."""
    check_origin(request, settings)


async def require_csrf(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    identity: Annotated[Identity, Depends(get_identity)],
) -> Identity:
    """Session + (for POST/PUT/PATCH/DELETE) allowed Origin and the session's CSRF token."""
    if request.method.upper() in UNSAFE_METHODS:
        check_origin(request, settings)
        supplied = request.headers.get(CSRF_HEADER)
        if not supplied or not tokens_equal(supplied, identity.csrf_token):
            raise AppError(403, "CSRF_INVALID", "CSRF token missing or invalid")
    return identity


# --- cookie ------------------------------------------------------------------------------------


def set_session_cookie(
    response: Response, settings: Settings, token: str, expires_at: datetime, now: datetime
) -> None:
    """Host-only, Secure, HttpOnly, SameSite=Lax cookie that lives for the remaining lifetime."""
    max_age = max(0, int((expires_at - now).total_seconds()))
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name, path="/", secure=True, httponly=True, samesite="lax"
    )
