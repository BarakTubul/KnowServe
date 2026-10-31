"""Operator test surface for the isolated M0 spike (contract: docs/contracts/jobs-outbox.md).

Create, list, inspect and manually retry jobs so the immediate-publish path and both recovery
paths can be exercised on a deployed spike. This is NOT application authentication (M1) and NOT
admin RBAC (M3 wraps the same ``knowserve_core.job_recovery`` functions for the Admin role).

Restrictions, all enforced here:

* mounted only when ``KS_ENABLE_SPIKE_JOB_OPS`` is true (which requires the operator email list
  and the token audience); otherwise the routes do not exist (404);
* the path is ``/internal/...``: the Pages Function forwards only ``/api/v1/*``, so these routes
  are unreachable from the public site; they are also hidden from the public OpenAPI;
* every call needs a Google ID token (``Authorization: Bearer``) for the configured audience whose
  verified email is on the operator allow-list. The proxy guard still applies on top;
* failure hooks (``skip_publish``, job type ``always_fail``) additionally need
  ``KS_ENABLE_SPIKE_FAILURE_HOOKS`` and are refused otherwise;
* at most ``MAX_OPEN_JOBS`` unfinished jobs can exist, bounding QStash publishes and DB growth.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.job_recovery import (
    ATTENTION_STATES,
    JobNotFoundError,
    JobView,
    NotRetryableError,
    create_job,
    get_job_view,
    list_job_views,
    retry_job,
)
from knowserve_core.qstash import Publisher
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

MAX_OPEN_JOBS = 50
TEST_JOB_TYPES = ("noop", "always_fail", "fail_then_ok")
HOOK_JOB_TYPES = frozenset({"always_fail", "fail_then_ok"})

router = APIRouter(prefix="/internal/spike/jobs", include_in_schema=False)


class JobCreate(BaseModel):
    job_type: Literal["noop", "always_fail", "fail_then_ok"] = "noop"
    skip_publish: bool = False


class JobOut(BaseModel):
    id: uuid.UUID
    job_type: str
    delivery_state: str
    job_status: str
    attempts: int
    publish_attempts: int
    last_error: str | None
    publish_error: str | None
    retry_action: str | None
    correlation_id: str
    created_at: datetime
    updated_at: datetime


class RetryOut(BaseModel):
    action: str
    published: bool
    job: JobOut


def _out(view: JobView) -> JobOut:
    return JobOut(
        id=view.job_id,
        job_type=view.job_type,
        delivery_state=view.delivery_state,
        job_status=view.job_status,
        attempts=view.attempts,
        publish_attempts=view.publish_attempts,
        last_error=view.last_error,
        publish_error=view.publish_error,
        retry_action=view.retry_action,
        correlation_id=view.correlation_id,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )


def _unauthenticated() -> AppError:
    return AppError(401, "UNAUTHENTICATED", "Authentication required")


async def require_operator(request: Request) -> None:
    """Verify the Google ID token. Every failure is the same generic 401."""
    state = request.app.state
    settings: Settings = state.settings
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token or not settings.spike_oidc_audience:
        raise _unauthenticated()
    try:
        claims = await asyncio.to_thread(state.oidc_verifier, token, settings.spike_oidc_audience)
    except Exception:
        raise _unauthenticated() from None
    email = claims.get("email")
    if (
        claims.get("email_verified") is not True
        or not isinstance(email, str)
        or email.lower() not in settings.spike_operator_emails
    ):
        raise _unauthenticated()


def _factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def _publisher(request: Request) -> Publisher:
    return request.app.state.publisher


def _windows(request: Request) -> dict[str, int]:
    settings: Settings = request.app.state.settings
    return {
        "grace_seconds": settings.publish_grace_seconds,
        "stuck_after_seconds": settings.stuck_after_seconds,
    }


@router.post("", status_code=201, dependencies=[Depends(require_operator)])
async def create_test_job(body: JobCreate, request: Request) -> JobOut:
    settings: Settings = request.app.state.settings
    hooks = body.skip_publish or body.job_type in HOOK_JOB_TYPES
    if hooks and not settings.enable_spike_failure_hooks:
        raise AppError(403, "FAILURE_HOOKS_DISABLED", "Test failure hooks are disabled")
    factory = _factory(request)
    async with factory() as session:
        open_jobs = (
            await session.execute(
                text("SELECT count(*) FROM jobs WHERE status IN ('queued', 'processing')")
            )
        ).scalar_one()
    if open_jobs >= MAX_OPEN_JOBS:
        raise AppError(429, "TOO_MANY_OPEN_JOBS", "Too many unfinished test jobs")
    job_id = await create_job(
        factory,
        _publisher(request),
        body.job_type,
        publish=not body.skip_publish,
        publish_timeout=settings.publish_timeout_seconds,
    )
    view = await get_job_view(factory, job_id, **_windows(request))
    assert view is not None
    return _out(view)


@router.get("", dependencies=[Depends(require_operator)])
async def list_test_jobs(
    request: Request,
    state: str = Query("attention", pattern="^(attention|all|[a-z_]+)$"),
    limit: int = Query(50, ge=1, le=100),
) -> list[JobOut]:
    states = None if state == "all" else ATTENTION_STATES if state == "attention" else {state}
    views = await list_job_views(
        _factory(request),
        states=frozenset(states) if states is not None else None,
        limit=limit,
        **_windows(request),
    )
    return [_out(v) for v in views]


@router.get("/{job_id}", dependencies=[Depends(require_operator)])
async def get_test_job(job_id: uuid.UUID, request: Request) -> JobOut:
    view = await get_job_view(_factory(request), job_id, **_windows(request))
    if view is None:
        raise AppError(404, "NOT_FOUND", "Job not found")
    return _out(view)


@router.post("/{job_id}/retry", dependencies=[Depends(require_operator)])
async def retry_test_job(job_id: uuid.UUID, request: Request) -> RetryOut:
    settings: Settings = request.app.state.settings
    factory = _factory(request)
    try:
        result = await retry_job(
            factory,
            _publisher(request),
            job_id,
            publish_timeout=settings.publish_timeout_seconds,
            **_windows(request),
        )
    except JobNotFoundError:
        raise AppError(404, "NOT_FOUND", "Job not found") from None
    except NotRetryableError as exc:
        raise AppError(
            409, "JOB_NOT_RETRYABLE", f"Job is {exc.state}; it cannot be retried now"
        ) from None
    view = await get_job_view(factory, job_id, **_windows(request))
    assert view is not None
    return RetryOut(action=result.action, published=result.published, job=_out(view))
