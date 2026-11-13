"""ZIP import: preview and confirm (M3-04).

Preview creates no row, object or job (ADM-12). Confirm receives the ZIP again and re-validates
everything (finding F1, ADM-11), then creates each valid entry through ``UploadService``.

Idempotency and resume (ADM-13, ADM-14): the first confirm under a key inserts an in-progress
``admin_idempotency_keys`` row (``result_status`` 0). Each entry is then created in its own
transaction together with its ``import_batch_entries`` row, so an entry exists exactly when it is
recorded. A confirm that died half way resumes under the same key (the same ZIP, checked by hash)
and skips recorded entries. Two concurrent confirms with one key race on the unique
``(idempotency_key_id, entry_key)``: the loser rolls back and reads the winner's outcome. When
every entry is recorded the key row gets the final 200 body, which later requests replay.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from knowserve_core import audit
from knowserve_core.identity import Identity
from knowserve_core.ingestion_contract import ADMIN_ERRORS, AdminErrorCode, Operation
from knowserve_core.models import AdminIdempotencyKey, Department, ImportBatchEntry
from knowserve_core.web import AppError

from ..schemas import DepartmentOut
from .archive import EntryPlan, inspect_zip, read_entry
from .creation import (
    IN_PROGRESS_STATUS,
    IdempotencyScope,
    UploadService,
    get_upload_service,
    request_hash,
)
from .deps import require_admin_csrf, require_uploads_enabled
from .schemas import (
    AdminDocumentOut,
    ImportConfirmResponse,
    ImportEntryPreview,
    ImportEntryResult,
    ImportPreviewResponse,
    admin_error_responses,
)
from .upload import IdempotencyKey, reject_unknown_form_fields
from .validation import read_upload, reject

router = APIRouter(tags=["admin"])


async def _read_zip(request: Request, file: UploadFile) -> bytes:
    await reject_unknown_form_fields(request, frozenset({"file"}))
    return await read_upload(
        file, request.app.state.settings.upload_max_zip_bytes, AdminErrorCode.ZIP_TOO_LARGE
    )


async def _plan(service: UploadService, data: bytes) -> list[EntryPlan]:
    async with service.session_factory() as session:
        rows = (await session.execute(select(Department))).scalars().all()
    departments = {r.slug: DepartmentOut(id=r.id, slug=r.slug, name=r.name) for r in rows}
    return await asyncio.to_thread(
        inspect_zip, data, service.settings, departments, service.pdf_check
    )


@router.post(
    "/imports/preview",
    response_model=ImportPreviewResponse,
    responses=admin_error_responses(401, 403, 413, 422, 503),
)
async def preview_import(
    request: Request,
    _: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    service: Annotated[UploadService, Depends(get_upload_service)],
    file: Annotated[UploadFile, File()],
) -> ImportPreviewResponse:
    # Validate the archive and every manifest entry. Creates nothing (ADM-12).
    data = await _read_zip(request, file)
    plans = await _plan(service, data)
    entries = [
        ImportEntryPreview(
            index=p.index,
            file=p.shown_file,
            title=p.title,
            owner_department=p.owner,
            allowed_departments=p.allowed,
            valid=p.valid,
            error_code=p.error_code,
            error_message=p.error_message,
            detail=p.detail,
        )
        for p in plans
    ]
    valid = sum(1 for e in entries if e.valid)
    return ImportPreviewResponse(
        entries=entries, valid_count=valid, invalid_count=len(entries) - valid
    )


def _result(plan: EntryPlan, outcome: ImportBatchEntry | None) -> ImportEntryResult:
    if outcome is not None and outcome.outcome == "created":
        return ImportEntryResult(
            index=plan.index,
            file=plan.shown_file,
            status="created",
            document_id=outcome.document_id,
        )
    code = AdminErrorCode(outcome.error_code) if outcome is not None else plan.error_code
    assert code is not None
    return ImportEntryResult(
        index=plan.index,
        file=plan.shown_file,
        status="rejected",
        error_code=code,
        error_message=ADMIN_ERRORS[code].message,
        detail=plan.detail,
    )


async def _recorded(service: UploadService, key_row_id: uuid.UUID) -> dict[str, ImportBatchEntry]:
    async with service.session_factory() as session:
        rows = (
            await session.execute(
                select(ImportBatchEntry).where(ImportBatchEntry.idempotency_key_id == key_row_id)
            )
        ).scalars()
        return {r.entry_key: r for r in rows}


async def _record_rejected(
    service: UploadService, key_row_id: uuid.UUID, entry_key: str, code: AdminErrorCode
) -> None:
    try:
        async with service.session_factory() as session, session.begin():
            session.add(
                ImportBatchEntry(
                    idempotency_key_id=key_row_id,
                    entry_key=entry_key,
                    outcome="rejected",
                    error_code=code.value,
                )
            )
    except IntegrityError:
        pass  # a concurrent confirm recorded this entry first


@router.post(
    "/imports/confirm",
    response_model=ImportConfirmResponse,
    responses=admin_error_responses(401, 403, 409, 413, 422, 429, 503),
)
async def confirm_import(
    request: Request,
    admin: Annotated[Identity, Depends(require_admin_csrf)],
    __: Annotated[None, Depends(require_uploads_enabled)],
    service: Annotated[UploadService, Depends(get_upload_service)],
    idempotency_key: IdempotencyKey,
    file: Annotated[UploadFile, File()],
) -> ImportConfirmResponse:
    """Partial success is a 200 with per-file results (ADM-14)."""
    data = await _read_zip(request, file)
    scope = IdempotencyScope(
        idempotency_key,
        Operation.CONFIRM_IMPORT,
        request_hash(Operation.CONFIRM_IMPORT, zip_sha256=hashlib.sha256(data).hexdigest()),
    )
    stored = await service.lookup(admin.user_id, idempotency_key)
    if stored is not None:
        service.check_scope(stored, scope)
        if not stored.in_progress:
            return ImportConfirmResponse.model_validate(stored.result)

    # Everything is validated again; nothing from the preview is trusted (ADM-11).
    plans = await _plan(service, data)

    key_row_id = stored.id if stored is not None else None
    recorded = await _recorded(service, key_row_id) if key_row_id else {}
    todo = [p for p in plans if p.valid and str(p.index) not in recorded]
    if todo:
        room = await service.headroom()
        if len(todo) > room.in_flight:
            raise reject(AdminErrorCode.UPLOAD_BACKLOG_FULL)
        if len(todo) > room.per_day:
            raise reject(AdminErrorCode.DAILY_UPLOAD_LIMIT)
    if key_row_id is None:
        try:
            async with service.session_factory() as session, session.begin():
                row = AdminIdempotencyKey(
                    admin_user_id=admin.user_id,
                    idempotency_key=scope.key,
                    operation=scope.operation.value,
                    request_hash=scope.request_hash,
                    result_status=IN_PROGRESS_STATUS,
                    result={"state": "in_progress"},
                )
                session.add(row)
                await session.flush()
                key_row_id = row.id
        except IntegrityError:  # a concurrent confirm with this key started first
            stored = await service.lookup(admin.user_id, idempotency_key)
            if stored is None:
                raise
            service.check_scope(stored, scope)
            if not stored.in_progress:
                return ImportConfirmResponse.model_validate(stored.result)
            key_row_id = stored.id
        recorded = await _recorded(service, key_row_id)

    results: list[ImportEntryResult] = []
    for plan in plans:
        entry_key = str(plan.index)
        outcome = recorded.get(entry_key)
        if outcome is None and not plan.valid:
            assert plan.error_code is not None
            await _record_rejected(service, key_row_id, entry_key, plan.error_code)
            outcome = (await _recorded(service, key_row_id)).get(entry_key)
        elif outcome is None:
            outcome = await _create_entry(service, admin.user_id, key_row_id, plan, data)
        results.append(_result(plan, outcome))

    body = ImportConfirmResponse(
        results=results,
        created_count=sum(1 for r in results if r.status == "created"),
        rejected_count=sum(1 for r in results if r.status == "rejected"),
    )
    async with service.session_factory() as session, session.begin():
        # Only the confirm that finishes the batch writes the result and the audit row.
        finished = await session.execute(
            update(AdminIdempotencyKey)
            .where(
                AdminIdempotencyKey.id == key_row_id,
                AdminIdempotencyKey.result_status == IN_PROGRESS_STATUS,
            )
            .values(result_status=200, result=body.model_dump(mode="json"))
        )
        if finished.rowcount == 1:  # type: ignore[attr-defined]
            await audit.record(
                session,
                "admin.import.confirmed",
                user_id=admin.user_id,
                created_count=body.created_count,
                rejected_count=body.rejected_count,
            )
    return body


async def _create_entry(
    service: UploadService,
    admin_id: uuid.UUID,
    key_row_id: uuid.UUID,
    plan: EntryPlan,
    data: bytes,
) -> ImportBatchEntry | None:
    """Create one valid entry and record it in the same transaction. Returns its recorded
    outcome. A limit or validation refusal is recorded as ``rejected``; an infrastructure
    failure propagates so the Admin can resume with the same key."""
    entry_key = str(plan.index)
    assert plan.owner is not None and plan.title is not None

    async def record(session: AsyncSession, out: AdminDocumentOut) -> None:
        document_id = out.document_id
        session.add(
            ImportBatchEntry(
                idempotency_key_id=key_row_id,
                entry_key=entry_key,
                outcome="created",
                document_id=document_id,
            )
        )
        await session.flush()

    try:
        pdf = await asyncio.to_thread(read_entry, data, plan.file, service.settings)
        await service.create_document(
            admin_id=admin_id,
            idempotency_key=None,
            filename=plan.file.rsplit("/", 1)[-1],
            data=pdf,
            title=plan.title,
            owner_department_id=plan.owner.id,
            allowed_department_ids=[d.id for d in plan.allowed],
            source="import",
            in_transaction=record,
        )
    except IntegrityError:
        pass  # a concurrent confirm created this entry; read its outcome below
    except AppError as exc:
        if exc.code not in AdminErrorCode.__members__:
            raise
        await _record_rejected(service, key_row_id, entry_key, AdminErrorCode(exc.code))
    return (await _recorded(service, key_row_id)).get(entry_key)
