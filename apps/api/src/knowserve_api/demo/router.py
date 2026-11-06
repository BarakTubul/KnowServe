"""Try Demo (M1-04, AUTH-16, AUTH-06, AUTH-15, SEC-10).

The browser signs in to Firebase anonymously and posts the ID token here. Only the ``anonymous``
provider is accepted. The Demo identity is a ``users`` row of kind ``demo`` keyed by the Firebase
uid. It cannot start a session after its own 24 hours (``DEMO_EXPIRED``), so reuse never extends it,
and a session started late is capped at the identity's 24 hours.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core import audit
from knowserve_core.clock import Clock
from knowserve_core.firebase_tokens import TokenVerifier
from knowserve_core.models import User
from knowserve_core.ratelimit import RateLimiter
from knowserve_core.sessions import SessionService
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from ..auth.deps import (
    get_clock,
    get_db,
    get_rate_limiter,
    get_session_service,
    get_settings_dep,
    get_token_verifier,
    require_origin,
    set_session_cookie,
    unauthenticated,
)
from ..auth.verification import verify_id_token_or_raise
from ..departments.service import build_identity_response
from ..schemas import IdentityResponse, IdTokenRequest, error_responses

router = APIRouter(prefix="/v1/demo", tags=["demo"])

UNKNOWN_IP = "unknown"


def client_ip(request: Request, settings: Settings) -> str:
    """The client IP the proxy guard vouches for; never read from ``X-Forwarded-For`` here.

    With the guard on (``KS_PROXY_SHARED_SECRET``) the guard has verified the shared secret and
    stored the Pages Function's ``X-KS-Client-IP`` in ``request.state.client_ip``; if that header
    was missing or malformed, all such requests share one conservative bucket. With the guard off
    (local development, tests) the direct peer address is used.
    """
    if settings.proxy_shared_secret is not None:
        return getattr(request.state, "client_ip", None) or UNKNOWN_IP
    return request.client.host if request.client else UNKNOWN_IP


@router.post(
    "/start",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 429, 503),
)
async def start_demo(
    body: IdTokenRequest,
    request: Request,
    response: Response,
    _origin: Annotated[None, Depends(require_origin)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    clock: Annotated[Clock, Depends(get_clock)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> IdentityResponse:
    """Start a Demo session from a fresh Firebase anonymous ID token (AUTH-16).

    401 ``DEMO_EXPIRED`` when this Demo identity is past its 24 hours.
    """
    verified = await verify_id_token_or_raise(verifier, body.id_token, require_fresh=True)
    ip = client_ip(request, settings)

    if verified.sign_in_provider != "anonymous":
        await audit.record(db, "demo.denied", ip=ip, reason="provider")
        await db.commit()
        raise unauthenticated()

    decision = await limiter.hit(
        db,
        f"demo:ip:{ip}",
        limit=settings.demo_start_limit,
        window_seconds=settings.demo_start_window_seconds,
    )
    if not decision.allowed:
        await audit.record(db, "demo.denied", ip=ip, reason="rate_limited")
        await db.commit()
        raise AppError(
            429,
            "RATE_LIMITED",
            "Too many Demo sessions started. Try again later.",
            headers={"Retry-After": str(max(1, decision.retry_after_seconds))},
        )

    now = clock.now()
    # Create-or-load in one statement pair; a concurrent start for the same uid is harmless.
    await db.execute(
        pg_insert(User)
        .values(firebase_uid=verified.uid, kind="demo", created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=[User.firebase_uid])
    )
    user = await db.scalar(select(User).where(User.firebase_uid == verified.uid))
    if user is None or user.kind != "demo" or user.disabled_at is not None:
        await audit.record(
            db,
            "demo.denied",
            user_id=user.id if user is not None else None,
            ip=ip,
            reason="not_demo",
        )
        await db.commit()
        raise unauthenticated()

    lifetime_end = user.created_at + timedelta(seconds=settings.session_ttl_seconds)
    if now >= lifetime_end:
        await audit.record(db, "demo.denied", user_id=user.id, ip=ip, reason="expired")
        await db.commit()
        raise AppError(401, "DEMO_EXPIRED", "This Demo has ended. Start a new Demo.")

    token, row = await service.create_session(
        db, user, "anonymous", department_id=user.last_active_department_id
    )
    if row.expires_at > lifetime_end:
        row.expires_at = lifetime_end  # a Demo identity never outlives its own 24 hours
    await audit.record(db, "demo.started", user_id=user.id, ip=ip)
    await db.commit()  # commit before the cookie is built or the response leaves

    identity = await service.lookup_by_token(db, token)
    assert identity is not None
    set_session_cookie(response, settings, token, identity.expires_at, now)
    return await build_identity_response(db, identity)
