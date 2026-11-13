"""The document creation service (M3-03). Callers: single upload, ZIP import (M3-04) and, for the
shared primitives, replacing a failed document (M3-05b).

One upload goes through ``UploadService.execute``:

1. Idempotency replay (``Idempotency-Key``, scoped to the Admin and the operation): the same key
   with the same request returns the stored result, the same key with another request is 409.
2. Store the bytes in R2 under a server-generated key ``documents/{document_id}/{revision_id}.pdf``
   (ADR 0010). No client input reaches a key.
3. One database transaction (ADM-03, ING-12): an advisory lock serializes the upload limits, the
   limits are checked again, ``apply`` writes the rows (document or revision, access, job and
   outbox through ``enqueue_job``, audit) and the idempotency row is written last, so it exists
   only if everything else does. If anything fails the transaction rolls back and the stored
   object is deleted.
4. After the commit, ``publish_after_commit`` tries to publish the job. It never raises; a lost
   publish shows as ``publish_failed`` or ``unpublished_stuck`` and the Admin retries (ADM-16).

Two concurrent requests with one key both try to insert the same unique idempotency row. The
second waits for the first to commit, fails on the unique key and rolls back, deletes its own
object and then replays the first result.

For M3-05b (replace): call ``validate_pdf_upload``, build ``IdempotencyScope`` with
``request_hash(...)``, and pass an ``apply`` that does the atomic ``failed -> queued`` conditional
update, then ``add_revision_with_job`` and an audit row, and returns the ``AdminDocumentOut``.
``execute(count_new_document=False)`` skips the per-day cap (a replacement is not a new document)
and still applies the in-flight cap.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from fastapi import Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core import audit
from knowserve_core.clock import Clock
from knowserve_core.ingestion_contract import (
    INGEST_JOB_TYPE,
    AdminErrorCode,
    Operation,
)
from knowserve_core.jobs import enqueue_job
from knowserve_core.models import (
    AdminIdempotencyKey,
    Department,
    Document,
    DocumentDepartmentAccess,
    DocumentRevision,
)
from knowserve_core.object_store import ObjectStore, ObjectStoreError
from knowserve_core.outbox import publish_after_commit
from knowserve_core.qstash import Publisher
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from ..schemas import DepartmentOut
from .schemas import AdminDocumentOut
from .validation import (
    MAX_ALLOWED_DEPARTMENTS,
    PdfCheck,
    check_pdf_structure,
    reject,
    validate_filename,
    validate_pdf,
    validate_title,
)

logger = logging.getLogger("knowserve.admin.upload")

# One transaction-scoped advisory lock serializes the in-flight and per-day limit checks, so two
# concurrent uploads cannot both pass at limit minus one.
UPLOAD_LIMITS_LOCK = 0x4B53_5550_4C44
# ``admin_idempotency_keys.result_status`` of a ZIP confirmation that is still running. Single
# operations never write it: their row is written once, complete, in the creating transaction.
IN_PROGRESS_STATUS = 0
REQUEST_HASH_VERSION = 1

ApplyFn = Callable[[AsyncSession, "PreparedRevision"], Awaitable[AdminDocumentOut]]


@dataclass(frozen=True)
class IdempotencyScope:
    key: str
    operation: Operation
    request_hash: str


@dataclass(frozen=True)
class StoredResult:
    id: uuid.UUID
    operation: str
    request_hash: str
    status: int
    result: dict[str, Any]

    @property
    def in_progress(self) -> bool:
        return self.status == IN_PROGRESS_STATUS


@dataclass
class PreparedRevision:
    """What ``apply`` needs to write one revision; ``add_revision_with_job`` sets ``job_id``."""

    document_id: uuid.UUID
    revision_id: uuid.UUID
    storage_key: str
    size_bytes: int
    now: datetime
    job_id: uuid.UUID | None = field(default=None)


@dataclass(frozen=True)
class UploadOutcome:
    status_code: int
    document: AdminDocumentOut
    replayed: bool


@dataclass(frozen=True)
class Headroom:
    in_flight: int
    per_day: int


def request_hash(operation: Operation, **parts: Any) -> str:
    """SHA-256 over a canonical encoding of the operation and its normalized request, so a replay
    with the same key but other content is detectable (ADM-13, ADM-18)."""
    body = json.dumps(
        {"v": REQUEST_HASH_VERSION, "op": operation.value, **parts},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def storage_key_for(document_id: uuid.UUID, revision_id: uuid.UUID) -> str:
    """The only way a storage key is built: server-generated ids, never client input."""
    return f"documents/{document_id}/{revision_id}.pdf"


def utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def load_departments(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Department]:
    rows = (await session.execute(select(Department).where(Department.id.in_(set(ids))))).scalars()
    return {row.id: row for row in rows}


def department_out(row: Department) -> DepartmentOut:
    return DepartmentOut(id=row.id, slug=row.slug, name=row.name)


async def add_revision_with_job(
    session: AsyncSession, prepared: PreparedRevision
) -> DocumentRevision:
    """Insert a ``queued`` revision with its ingestion job and outbox row (ING-12, ING-21).

    Must run inside the ``apply`` transaction, after the document row exists."""
    job = await enqueue_job(session, INGEST_JOB_TYPE)
    prepared.job_id = job.id
    revision = DocumentRevision(
        id=prepared.revision_id,
        document_id=prepared.document_id,
        storage_key=prepared.storage_key,
        status="queued",
        size_bytes=prepared.size_bytes,
        content_type="application/pdf",
        job_id=job.id,
        created_at=prepared.now,
    )
    session.add(revision)
    await session.flush()
    return revision


class _AlreadyDone(Exception):
    """Another request with the same idempotency key committed while this one waited."""


class UploadService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        object_store: ObjectStore,
        publisher: Publisher,
        settings: Settings,
        clock: Clock,
        pdf_check: PdfCheck = check_pdf_structure,
    ) -> None:
        self._sf = session_factory
        self._store = object_store
        self._publisher = publisher
        self._settings = settings
        self._clock = clock
        self._pdf_check = pdf_check

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._sf

    @property
    def pdf_check(self) -> PdfCheck:
        return self._pdf_check

    # --- validation -------------------------------------------------------------------------

    def validate_pdf_upload(self, filename: str | None, data: bytes) -> str:
        """Name and content checks (SEC-11, ADM-10). Returns the sanitized file name. Pure."""
        return validate_pdf(filename, data, self._pdf_check)

    # --- idempotency -------------------------------------------------------------------------

    async def lookup(self, admin_id: uuid.UUID, key: str) -> StoredResult | None:
        async with self._sf() as session:
            row = (
                await session.execute(
                    select(AdminIdempotencyKey).where(
                        AdminIdempotencyKey.admin_user_id == admin_id,
                        AdminIdempotencyKey.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        return StoredResult(
            row.id, row.operation, row.request_hash, row.result_status, dict(row.result)
        )

    @staticmethod
    def check_scope(stored: StoredResult, scope: IdempotencyScope) -> None:
        """409 ``IDEMPOTENCY_KEY_REUSED`` unless the stored row is for the same operation and the
        same request."""
        if stored.operation != scope.operation.value or stored.request_hash != scope.request_hash:
            raise reject(AdminErrorCode.IDEMPOTENCY_KEY_REUSED)

    @staticmethod
    def add_idempotency_row(
        session: AsyncSession,
        admin_id: uuid.UUID,
        scope: IdempotencyScope,
        status: int,
        result: dict[str, Any],
    ) -> None:
        session.add(
            AdminIdempotencyKey(
                admin_user_id=admin_id,
                idempotency_key=scope.key,
                operation=scope.operation.value,
                request_hash=scope.request_hash,
                result_status=status,
                result=result,
            )
        )

    # --- limits ------------------------------------------------------------------------------

    async def _counts(self, session: AsyncSession) -> tuple[int, int]:
        in_flight = await session.scalar(
            select(func.count())
            .select_from(DocumentRevision)
            .join(Document, Document.id == DocumentRevision.document_id)
            .where(
                Document.deleted_at.is_(None), DocumentRevision.status.in_(("queued", "processing"))
            )
        )
        today = await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.created_at >= utc_day_start(self._clock.now()))
        )
        return int(in_flight or 0), int(today or 0)

    async def headroom(self) -> Headroom:
        """How many more documents may be queued now, and created today (D1). Advisory: the
        authoritative check runs again inside the creating transaction."""
        async with self._sf() as session:
            in_flight, today = await self._counts(session)
        return Headroom(
            in_flight=max(0, self._settings.upload_max_in_flight - in_flight),
            per_day=max(0, self._settings.upload_max_per_day - today),
        )

    async def _enforce_limits(self, session: AsyncSession, *, count_new_document: bool) -> None:
        in_flight, today = await self._counts(session)
        if in_flight >= self._settings.upload_max_in_flight:
            raise reject(AdminErrorCode.UPLOAD_BACKLOG_FULL)
        if count_new_document and today >= self._settings.upload_max_per_day:
            raise reject(AdminErrorCode.DAILY_UPLOAD_LIMIT)

    async def precheck_limits(self, *, count_new_document: bool = True) -> None:
        async with self._sf() as session:
            await self._enforce_limits(session, count_new_document=count_new_document)

    # --- the shared transaction --------------------------------------------------------------

    async def execute(
        self,
        *,
        admin_id: uuid.UUID,
        scope: IdempotencyScope | None,
        document_id: uuid.UUID,
        data: bytes,
        apply: ApplyFn,
        count_new_document: bool = True,
    ) -> UploadOutcome:
        """Store the object and run ``apply`` in one transaction (see the module docstring).

        ``scope`` is ``None`` for a ZIP entry, whose idempotency is the batch row and
        ``import_batch_entries`` written by ``apply``. Without a scope an ``IntegrityError`` from
        ``apply`` is re-raised after the cleanup so the caller can resolve it."""
        if scope is not None:
            stored = await self.lookup(admin_id, scope.key)
            if stored is not None:
                return self._replay(stored, scope)
        await self.precheck_limits(count_new_document=count_new_document)

        revision_id = uuid.uuid4()
        key = storage_key_for(document_id, revision_id)
        try:
            await self._store.put(key, data, "application/pdf")
        except ObjectStoreError:
            raise AppError(
                503, "DEPENDENCY_UNAVAILABLE", "A required service is unavailable"
            ) from None
        prepared = PreparedRevision(
            document_id=document_id,
            revision_id=revision_id,
            storage_key=key,
            size_bytes=len(data),
            now=self._clock.now(),
        )
        try:
            async with self._sf() as session, session.begin():
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:k)"), {"k": UPLOAD_LIMITS_LOCK}
                )
                if scope is not None and await session.scalar(
                    select(AdminIdempotencyKey.id).where(
                        AdminIdempotencyKey.admin_user_id == admin_id,
                        AdminIdempotencyKey.idempotency_key == scope.key,
                    )
                ):
                    raise _AlreadyDone  # replay instead of failing a limit this request caused
                await self._enforce_limits(session, count_new_document=count_new_document)
                document = await apply(session, prepared)
                if scope is not None:
                    self.add_idempotency_row(
                        session, admin_id, scope, 202, document.model_dump(mode="json")
                    )
                    await session.flush()
        except (IntegrityError, _AlreadyDone):
            await self._discard(key, revision_id)
            if scope is not None:
                stored = await self.lookup(admin_id, scope.key)
                if stored is not None:
                    return self._replay(stored, scope)
            raise
        except BaseException:
            await self._discard(key, revision_id)
            raise
        if prepared.job_id is not None:
            await publish_after_commit(
                self._sf,
                self._publisher,
                prepared.job_id,
                publish_timeout=self._settings.publish_timeout_seconds,
            )
        return UploadOutcome(status_code=202, document=document, replayed=False)

    def _replay(self, stored: StoredResult, scope: IdempotencyScope) -> UploadOutcome:
        self.check_scope(stored, scope)
        if stored.in_progress:  # not written by single operations; treat as a different request
            raise reject(AdminErrorCode.IDEMPOTENCY_KEY_REUSED)
        return UploadOutcome(
            status_code=stored.status,
            document=AdminDocumentOut.model_validate(stored.result),
            replayed=True,
        )

    async def _discard(self, key: str, revision_id: uuid.UUID) -> None:
        """Delete the stored object after a failed transaction (M3-AC03). If the database cannot
        confirm that the revision row is absent (a commit may have succeeded before the
        connection broke), the object is kept and its key is logged for the M5 sweep."""

        async def _run() -> None:
            try:
                async with self._sf() as session:
                    committed = (
                        await session.execute(
                            select(DocumentRevision.id).where(DocumentRevision.id == revision_id)
                        )
                    ).first()
                if committed is not None:
                    return
                await self._store.delete(key)
            except Exception as exc:
                logger.warning(
                    "uploaded object left for cleanup",
                    extra={"storage_key": key, "error_type": type(exc).__name__},
                )

        await asyncio.shield(_run())

    # --- single upload -----------------------------------------------------------------------

    async def create_document(
        self,
        *,
        admin_id: uuid.UUID,
        idempotency_key: str | None,
        filename: str | None,
        data: bytes,
        title: str,
        owner_department_id: uuid.UUID,
        allowed_department_ids: Sequence[uuid.UUID] | None,
        source: Literal["single", "import"] = "single",
        in_transaction: Callable[[AsyncSession, AdminDocumentOut], Awaitable[None]] | None = None,
    ) -> UploadOutcome:
        """Validate and create one document with its first revision, access rows, job and outbox
        row (ADM-03, ADM-04, ADM-05, ADM-10).

        ``allowed_department_ids`` is explicit: ``None`` is ``ALLOWED_DEPARTMENTS_MISSING``, an
        empty list ``ALLOWED_DEPARTMENTS_EMPTY``. Nothing is derived from the owner. ``source``
        only labels the audit event. ``in_transaction`` (ZIP import) runs inside the creating
        transaction with the new document, so its own rows commit or roll back with it."""
        clean_title = validate_title(title)
        if allowed_department_ids is None:
            raise reject(AdminErrorCode.ALLOWED_DEPARTMENTS_MISSING)
        if len(allowed_department_ids) > MAX_ALLOWED_DEPARTMENTS:
            raise AppError(422, "VALIDATION_ERROR", "Too many allowed departments")
        allowed = sorted(set(allowed_department_ids), key=str)
        if not allowed:
            raise reject(AdminErrorCode.ALLOWED_DEPARTMENTS_EMPTY)
        label = validate_filename(filename)
        scope: IdempotencyScope | None = None
        if idempotency_key is not None:
            scope = IdempotencyScope(
                idempotency_key,
                Operation.CREATE_DOCUMENT,
                request_hash(
                    Operation.CREATE_DOCUMENT,
                    file_sha256=hashlib.sha256(data).hexdigest(),
                    filename=label,
                    title=clean_title,
                    owner=str(owner_department_id),
                    allowed=[str(item) for item in allowed],
                ),
            )
            stored = await self.lookup(admin_id, scope.key)
            if stored is not None:
                return self._replay(stored, scope)
        self.validate_pdf_upload(filename, data)
        async with self._sf() as session:
            departments = await load_departments(session, [owner_department_id, *allowed])
        if owner_department_id not in departments or any(d not in departments for d in allowed):
            raise reject(AdminErrorCode.UNKNOWN_DEPARTMENT)

        document_id = uuid.uuid4()

        async def apply(session: AsyncSession, prepared: PreparedRevision) -> AdminDocumentOut:
            session.add(
                Document(
                    id=document_id,
                    title=clean_title,
                    filename=label,
                    owner_department_id=owner_department_id,
                    created_at=prepared.now,
                    updated_at=prepared.now,
                )
            )
            await session.flush()
            await add_revision_with_job(session, prepared)
            for department_id in allowed:
                session.add(
                    DocumentDepartmentAccess(document_id=document_id, department_id=department_id)
                )
            await session.flush()
            await audit.record(
                session,
                "admin.document.created",
                user_id=admin_id,
                document_id=str(document_id),
                revision_id=str(prepared.revision_id),
                owner_department_id=str(owner_department_id),
                allowed_department_ids=[str(item) for item in allowed],
                size_bytes=prepared.size_bytes,
                source=source,
            )
            out = AdminDocumentOut(
                document_id=document_id,
                revision_id=prepared.revision_id,
                status="queued",
                can_retry=False,
                can_replace=False,
                title=clean_title,
                filename=label,
                owner_department=department_out(departments[owner_department_id]),
                allowed_departments=[
                    department_out(departments[d])
                    for d in sorted(allowed, key=lambda item: departments[item].position)
                ],
                size_bytes=prepared.size_bytes,
                created_at=prepared.now,
                updated_at=prepared.now,
            )
            if in_transaction is not None:
                await in_transaction(session, out)
            return out

        return await self.execute(
            admin_id=admin_id,
            scope=scope,
            document_id=document_id,
            data=data,
            apply=apply,
        )


def get_upload_service(request: Request) -> UploadService:
    """The service for one request, built from the app state. ``app.state.pdf_check`` (optional)
    swaps in the M3-02a structural check."""
    state = request.app.state
    return UploadService(
        session_factory=state.session_factory,
        object_store=state.object_store,
        publisher=state.publisher,
        settings=state.settings,
        clock=state.clock,
        pdf_check=getattr(state, "pdf_check", check_pdf_structure),
    )
