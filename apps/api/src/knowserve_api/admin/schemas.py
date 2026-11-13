"""M3 Admin request and response models: the shared contract (docs/contracts/admin-api.md).

Owner-written in M3-01. Slices implement the routes behind these models; changing a model needs
Owner approval and regenerating ``docs/contracts/openapi.json`` (WF-03). Slices add their own
helper models in their own modules, not here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from knowserve_core.ingestion_contract import AdminErrorCode, FailureCode, Phase
from knowserve_core.job_recovery import DeliveryState
from knowserve_core.web import ErrorBody

from ..schemas import DepartmentOut

RevisionStatus = Literal["queued", "processing", "ready", "failed"]


# --- Documents -----------------------------------------------------------------------------------


class DocumentProcessingStatus(BaseModel):
    """What the status stream sends (`event: status`) and what every Admin document carries.

    Built from the database of the document's latest revision (ADM-02). ``failure_message`` is the
    English fallback; the interface languages come from the frontend catalog by ``failure_code``.
    ``can_retry`` and ``can_replace`` are derived on the server so the client keeps no rules.
    """

    document_id: uuid.UUID
    revision_id: uuid.UUID
    status: RevisionStatus
    phase: Phase | None = None
    failure_code: FailureCode | None = None
    failure_message: str | None = None
    delivery_state: DeliveryState | None = None
    can_retry: bool
    can_replace: bool


class AdminDocumentOut(DocumentProcessingStatus):
    title: str
    filename: str
    owner_department: DepartmentOut
    allowed_departments: list[DepartmentOut]
    page_count: int | None = None
    size_bytes: int
    created_at: datetime
    updated_at: datetime


class AdminDocumentList(BaseModel):
    """Cursor page in the style of the library list (DOC-01). No total count."""

    items: list[AdminDocumentOut]
    next_cursor: str | None = None
    has_more: bool


class AccessUpdateRequest(BaseModel):
    """Replaces the allowed departments (ADM-07). An empty list is 422
    ``ALLOWED_DEPARTMENTS_EMPTY``; the field is not constrained here so the route can return that
    stable code (ADM-05)."""

    allowed_department_ids: list[uuid.UUID]


# --- ZIP import ----------------------------------------------------------------------------------


class ImportEntryPreview(BaseModel):
    """One manifest entry as validated by the backend (ADM-12). Nothing was created."""

    index: int
    file: str
    title: str | None = None
    owner_department: DepartmentOut | None = None
    allowed_departments: list[DepartmentOut] = []
    valid: bool
    error_code: AdminErrorCode | None = None
    error_message: str | None = None
    # The offending value, for example an unknown department slug.
    detail: str | None = None


class ImportPreviewResponse(BaseModel):
    entries: list[ImportEntryPreview]
    valid_count: int
    invalid_count: int


class ImportEntryResult(BaseModel):
    """Per-file outcome of a confirmation (ADM-14)."""

    index: int
    file: str
    status: Literal["created", "rejected"]
    document_id: uuid.UUID | None = None
    error_code: AdminErrorCode | None = None
    error_message: str | None = None
    detail: str | None = None


class ImportConfirmResponse(BaseModel):
    results: list[ImportEntryResult]
    created_count: int
    rejected_count: int


# --- Errors --------------------------------------------------------------------------------------


class AdminErrorBody(ErrorBody):
    """The shared error body with the Admin codes of M3 spelled out in the schema, so the
    frontend catalog is checked against them at compile time. Other routes keep other codes."""

    code: AdminErrorCode | str  # type: ignore[assignment]


class AdminErrorEnvelope(BaseModel):
    error: AdminErrorBody


def admin_error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries for Admin routes."""
    return {status: {"model": AdminErrorEnvelope} for status in statuses}
