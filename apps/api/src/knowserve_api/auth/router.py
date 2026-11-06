"""Auth routes (owner: Backend-Auth, M1-02b).

Error codes (docs/contracts/auth-session.md): 401 UNAUTHENTICATED / REAUTH_REQUIRED, 403
EMAIL_NOT_VERIFIED / CSRF_INVALID / ORIGIN_INVALID, 409 CONFLICT, 429 RATE_LIMITED, 503
DEPENDENCY_UNAVAILABLE.

Every route that changes state commits BEFORE it builds the cookie or the response: ``get_db`` does
not auto-commit, so a missed commit would silently lose the session.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core import audit
from knowserve_core.clock import Clock
from knowserve_core.firebase_tokens import TokenVerifier, VerifiedToken
from knowserve_core.identity import Identity
from knowserve_core.models import Department, Session, User
from knowserve_core.sessions import SessionService
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from ..schemas import (
    DepartmentOut,
    IdentityResponse,
    IdTokenRequest,
    RevokeAllResponse,
    error_responses,
)
from .deps import (
    clear_session_cookie,
    get_clock,
    get_db,
    get_identity,
    get_session_service,
    get_settings_dep,
    get_token_verifier,
    require_csrf,
    require_origin,
    set_session_cookie,
    unauthenticated,
)
from .service import (
    EmailTaken,
    convert_locked_demo_user,
    create_registered,
    deny,
    email_owner,
    identity_response,
    lock_user_by_uid,
    require_verified,
)
from .verification import verify_id_token_or_raise

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    forwarded = getattr(request.state, "client_ip", None)
    if forwarded:
        return str(forwarded)
    return request.client.host if request.client else None


async def _issue_session(
    *,
    db: AsyncSession,
    service: SessionService,
    settings: Settings,
    clock: Clock,
    response: Response,
    user: User,
    provider: str,
    ip: str | None,
) -> IdentityResponse:
    """Create the session, COMMIT, then set the cookie and build the body."""
    token, row = await service.create_session(db, user, provider, user.last_active_department_id)
    await audit.record(db, "auth.session.created", user_id=user.id, ip=ip, provider=provider)
    body = await _snapshot(db, user, row, provider)
    await db.commit()
    set_session_cookie(response, settings, token, body.expires_at, clock.now())
    return body


async def _snapshot(db: AsyncSession, user: User, row: Session, provider: str) -> IdentityResponse:
    department = None
    if row.active_department_id is not None:
        dept = await db.get(Department, row.active_department_id)
        if dept is not None:
            department = DepartmentOut(id=dept.id, slug=dept.slug, name=dept.name)
    return IdentityResponse(
        kind=user.kind,  # type: ignore[arg-type]  # constrained by users_kind
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        sign_in_provider=provider,  # type: ignore[arg-type]
        active_department=department,
        expires_at=row.expires_at,
        csrf_token=row.csrf_secret,
    )


async def _check_token_rules(db: AsyncSession, verified: VerifiedToken, ip: str | None) -> str:
    try:
        return require_verified(verified)
    except AppError as exc:
        reason = "email_not_verified" if exc.status_code == 403 else "provider_or_email"
        await deny(db, reason, exc, ip=ip)


@router.post(
    "/session",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 429, 503),
)
async def create_session(
    body: IdTokenRequest,
    request: Request,
    response: Response,
    _origin: Annotated[None, Depends(require_origin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    clock: Annotated[Clock, Depends(get_clock)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> IdentityResponse:
    """Verify a fresh Firebase ID token (password or Google) and start a KnowServe session."""
    ip = _client_ip(request)
    verified = await verify_id_token_or_raise(verifier, body.id_token, require_fresh=True)
    email = await _check_token_rules(db, verified, ip)

    user = await lock_user_by_uid(db, verified.uid)
    if user is None:
        if await email_owner(db, email) is not None:
            await deny(db, "email_in_use", unauthenticated(), ip=ip)
        user = await create_registered(db, verified.uid, email, verified.name)
        if user is None:  # lost a race on uid or email: read once more, otherwise refuse
            user = await lock_user_by_uid(db, verified.uid)
        if user is None:
            await deny(db, "email_in_use", unauthenticated(), ip=ip)
    if user.disabled_at is not None:
        await deny(db, "user_disabled", unauthenticated(), user_id=user.id, ip=ip)

    if user.kind == "demo":  # pending conversion completed by the normal exchange (AUTH-34)
        try:
            await convert_locked_demo_user(db, user, email, verified.name, clock.now())
        except EmailTaken:
            await deny(db, "email_in_use", unauthenticated(), user_id=user.id, ip=ip)
        await service.revoke_all_for_user(db, user.id)
        await audit.record(db, "auth.account.converted", user_id=user.id, ip=ip, via="session")

    # Rotate: a session presented by the incoming cookie never survives a new login (AUTH-06).
    incoming = request.cookies.get(settings.session_cookie_name)
    previous = await service.lookup_by_token(db, incoming) if incoming else None
    if previous is not None:
        await service.revoke_session(db, previous.session_id)

    return await _issue_session(
        db=db,
        service=service,
        settings=settings,
        clock=clock,
        response=response,
        user=user,
        provider=verified.sign_in_provider,
        ip=ip,
    )


@router.post(
    "/convert",
    response_model=IdentityResponse,
    responses=error_responses(401, 403, 409, 503),
)
async def convert_demo(
    body: IdTokenRequest,
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    clock: Annotated[Clock, Depends(get_clock)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> IdentityResponse:
    """Convert the current Demo identity to Registered after a successful credential link."""
    # Repeats: with the (revoked) Demo cookie a repeat is 401, with the new Registered cookie it is
    # 409 CONFLICT. Concurrent calls: one converts; a call that already resolved its Demo session
    # finds the row registered with the same email and also succeeds (own new session); a call that
    # resolves the session after the commit gets 401 (the Demo session is revoked).
    ip = _client_ip(request)
    if identity.kind != "demo":
        raise AppError(409, "CONFLICT", "This account is already registered")
    verified = await verify_id_token_or_raise(verifier, body.id_token, require_fresh=False)
    if verified.uid != identity.firebase_uid:
        await deny(db, "uid_mismatch", unauthenticated(), user_id=identity.user_id, ip=ip)
    email = await _check_token_rules(db, verified, ip)

    user = await lock_user_by_uid(db, verified.uid)
    if user is None:  # Demo cleanup won the race: never resurrect
        await deny(db, "demo_user_gone", unauthenticated(), ip=ip)
    if user.disabled_at is not None:
        await deny(db, "user_disabled", unauthenticated(), user_id=user.id, ip=ip)
    # Re-check under the lock: a logout or sign-out-everywhere in another tab while this call was
    # in flight must still count (review finding 2).
    if await db.scalar(select(Session.revoked_at).where(Session.id == identity.session_id)):
        await deny(db, "session_revoked", unauthenticated(), user_id=user.id, ip=ip)
    conflict = AppError(409, "CONFLICT", "This email is already in use")
    if user.kind == "demo":
        try:
            await convert_locked_demo_user(db, user, email, verified.name, clock.now())
        except EmailTaken:
            await deny(db, "email_in_use", conflict, user_id=user.id, ip=ip)
        await audit.record(db, "auth.account.converted", user_id=user.id, ip=ip, via="convert")
        await service.revoke_all_for_user(db, user.id)
    elif user.kind != "registered" or user.email != email:
        await deny(db, "convert_not_applicable", conflict, user_id=user.id, ip=ip)
    else:
        # A concurrent call already converted: revoke only this call's own Demo session, never
        # the winner's new session (review finding 1).
        await service.revoke_session(db, identity.session_id)

    return await _issue_session(
        db=db,
        service=service,
        settings=settings,
        clock=clock,
        response=response,
        user=user,
        provider=verified.sign_in_provider,
        ip=ip,
    )


@router.post("/logout", status_code=204, responses=error_responses(401, 403))
async def logout(
    request: Request,
    identity: Annotated[Identity, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> Response:
    await service.revoke_session(db, identity.session_id)
    await audit.record(db, "auth.session.revoked", user_id=identity.user_id, ip=_client_ip(request))
    await db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=IdentityResponse, responses=error_responses(401))
async def me(
    identity: Annotated[Identity, Depends(get_identity)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IdentityResponse:
    return await identity_response(db, identity)


@router.post(
    "/sessions/revoke-all",
    response_model=RevokeAllResponse,
    responses=error_responses(401, 403),
)
async def revoke_all_sessions(
    request: Request,
    response: Response,
    identity: Annotated[Identity, Depends(require_csrf)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    service: Annotated[SessionService, Depends(get_session_service)],
) -> RevokeAllResponse:
    """Sign out everywhere: revoke every KnowServe session of the current user (AUTH-33)."""
    revoked = await service.revoke_all_for_user(db, identity.user_id)
    await audit.record(
        db,
        "auth.sessions.revoked_all",
        user_id=identity.user_id,
        ip=_client_ip(request),
        revoked=revoked,
    )
    await db.commit()
    clear_session_cookie(response, settings)
    return RevokeAllResponse(revoked=revoked)
