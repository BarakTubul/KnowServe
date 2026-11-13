"""M3 shared contracts for upload and ingestion (docs/contracts/admin-api.md, OPEN-31).

Owner-written in M3-01. Slices use these names and do not redefine them. Changing a code, a phase
or the event shape needs Owner approval (WF-03). The English texts here are the server-side
fallback; the interface languages come from the frontend catalogs keyed by the same codes
(PROD-13, OPEN-31 D8).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

# --- Job and pipeline ----------------------------------------------------------------------

INGEST_JOB_TYPE = "ingest_revision"

# Written to ``document_revisions.phase`` before each stage (ING-07). There are no percentages.
PHASES: tuple[str, ...] = ("fetching", "extracting", "chunking", "embedding", "publishing")
Phase = Literal["fetching", "extracting", "chunking", "embedding", "publishing"]

# text-embedding-3-small (ING-18). The migration pins the same number; changing it needs a new
# migration and a re-embed.
EMBEDDING_DIMENSIONS = 1536

# Page-bound chunks (ING-02, OPEN-03). Tunable through settings; these are the defaults.
DEFAULT_CHUNK_SIZE_TOKENS = 512
DEFAULT_CHUNK_OVERLAP_TOKENS = 64

MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1


def build_index_identity(
    embedding_model: str, dimensions: int, chunk_size_tokens: int, chunk_overlap_tokens: int
) -> str:
    """The identity stored per revision (ING-18). A query across two identities is refused."""
    return f"{embedding_model}:{dimensions}:c{chunk_size_tokens}o{chunk_overlap_tokens}"


# --- Failure codes (Worker side, stored in document_revisions.failure_reason) ---------------


class FailureCode(StrEnum):
    # Terminal: retrying the same file cannot help (ING-23). Replace the file instead.
    NO_EXTRACTABLE_TEXT = "NO_EXTRACTABLE_TEXT"
    INVALID_PDF = "INVALID_PDF"
    PDF_ENCRYPTED = "PDF_ENCRYPTED"
    TOO_MANY_PAGES = "TOO_MANY_PAGES"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    # Retried automatically until the attempt cap, then failed with a Retry button.
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
    PROCESSING_CRASHED = "PROCESSING_CRASHED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class FailureSpec:
    retryable: bool
    message: str


FAILURES: dict[FailureCode, FailureSpec] = {
    FailureCode.NO_EXTRACTABLE_TEXT: FailureSpec(
        False,
        "No readable text was found in this PDF. It may be a scan or contain only images. "
        "Upload a version with selectable text.",
    ),
    FailureCode.INVALID_PDF: FailureSpec(
        False, "This file could not be opened as a PDF. Upload a different file."
    ),
    FailureCode.PDF_ENCRYPTED: FailureSpec(
        False, "This PDF is password protected. Upload a version without a password."
    ),
    FailureCode.TOO_MANY_PAGES: FailureSpec(
        False, "This PDF has more pages than the limit. Upload a shorter file."
    ),
    FailureCode.DOCUMENT_DELETED: FailureSpec(
        False, "The document was deleted while it was being processed."
    ),
    FailureCode.STORAGE_UNAVAILABLE: FailureSpec(
        True, "The file could not be read from storage. Try again in a few minutes."
    ),
    FailureCode.EMBEDDING_FAILED: FailureSpec(
        True, "The text could not be prepared for search. Try again in a few minutes."
    ),
    FailureCode.PROCESSING_TIMEOUT: FailureSpec(
        True, "Processing took too long. Try again, or upload a smaller file."
    ),
    FailureCode.PROCESSING_CRASHED: FailureSpec(
        True, "Processing stopped unexpectedly. Try again, or upload a different file."
    ),
    FailureCode.INTERNAL_ERROR: FailureSpec(
        True, "Something went wrong while processing this document. Try again."
    ),
}


def failure_message(code: str | None) -> str | None:
    """The English fallback message for a stored failure code, or None for no failure."""
    if code is None:
        return None
    try:
        return FAILURES[FailureCode(code)].message
    except ValueError:
        return FAILURES[FailureCode.INTERNAL_ERROR].message


# --- Admin API error codes (HTTP envelope ``error.code``) ------------------------------------


class AdminErrorCode(StrEnum):
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    # Single PDF (SEC-11, ADM-10)
    FILE_EMPTY = "FILE_EMPTY"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    NOT_A_PDF = "NOT_A_PDF"
    INVALID_FILENAME = "INVALID_FILENAME"
    TITLE_INVALID = "TITLE_INVALID"
    # Departments (ADM-04, ADM-05, ADM-12)
    UNKNOWN_DEPARTMENT = "UNKNOWN_DEPARTMENT"
    ALLOWED_DEPARTMENTS_MISSING = "ALLOWED_DEPARTMENTS_MISSING"
    ALLOWED_DEPARTMENTS_EMPTY = "ALLOWED_DEPARTMENTS_EMPTY"
    # ZIP archive and manifest (ADM-11, SEC-11)
    ZIP_INVALID = "ZIP_INVALID"
    ZIP_TOO_LARGE = "ZIP_TOO_LARGE"
    ZIP_TOO_MANY_FILES = "ZIP_TOO_MANY_FILES"
    ZIP_UNSAFE_PATH = "ZIP_UNSAFE_PATH"
    ZIP_SYMLINK = "ZIP_SYMLINK"
    ZIP_RATIO_EXCEEDED = "ZIP_RATIO_EXCEEDED"
    ZIP_UNCOMPRESSED_TOO_LARGE = "ZIP_UNCOMPRESSED_TOO_LARGE"
    ZIP_NESTED_ARCHIVE = "ZIP_NESTED_ARCHIVE"
    ZIP_ENCRYPTED = "ZIP_ENCRYPTED"
    ZIP_DUPLICATE_NAME = "ZIP_DUPLICATE_NAME"
    ZIP_UNLISTED_FILE = "ZIP_UNLISTED_FILE"
    MANIFEST_MISSING = "MANIFEST_MISSING"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    MANIFEST_VERSION_UNSUPPORTED = "MANIFEST_VERSION_UNSUPPORTED"
    MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"
    MANIFEST_FILE_MISSING = "MANIFEST_FILE_MISSING"
    # State and limits (ADM-16, ADM-18, ADM-13, OPEN-31 D1, D14)
    DOCUMENT_NOT_REPLACEABLE = "DOCUMENT_NOT_REPLACEABLE"
    DOCUMENT_NOT_RETRYABLE = "DOCUMENT_NOT_RETRYABLE"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    UPLOAD_BACKLOG_FULL = "UPLOAD_BACKLOG_FULL"
    DAILY_UPLOAD_LIMIT = "DAILY_UPLOAD_LIMIT"
    UPLOADS_DISABLED = "UPLOADS_DISABLED"


@dataclass(frozen=True)
class ErrorSpec:
    status: int
    message: str


ADMIN_ERRORS: dict[AdminErrorCode, ErrorSpec] = {
    AdminErrorCode.DOCUMENT_NOT_FOUND: ErrorSpec(404, "This document was not found."),
    AdminErrorCode.FILE_EMPTY: ErrorSpec(422, "The file is empty."),
    AdminErrorCode.FILE_TOO_LARGE: ErrorSpec(413, "The file is larger than the allowed size."),
    AdminErrorCode.NOT_A_PDF: ErrorSpec(422, "Only PDF files can be uploaded."),
    AdminErrorCode.INVALID_FILENAME: ErrorSpec(422, "The file name is not allowed."),
    AdminErrorCode.TITLE_INVALID: ErrorSpec(422, "Enter a title of 1 to 200 characters."),
    AdminErrorCode.UNKNOWN_DEPARTMENT: ErrorSpec(422, "One of the departments does not exist."),
    AdminErrorCode.ALLOWED_DEPARTMENTS_MISSING: ErrorSpec(
        422, "Choose which departments can read this document."
    ),
    AdminErrorCode.ALLOWED_DEPARTMENTS_EMPTY: ErrorSpec(
        422, "Choose at least one department that can read this document."
    ),
    AdminErrorCode.ZIP_INVALID: ErrorSpec(422, "This is not a valid ZIP file."),
    AdminErrorCode.ZIP_TOO_LARGE: ErrorSpec(413, "The ZIP file is larger than the allowed size."),
    AdminErrorCode.ZIP_TOO_MANY_FILES: ErrorSpec(
        422, "The ZIP file contains more documents than the limit."
    ),
    AdminErrorCode.ZIP_UNSAFE_PATH: ErrorSpec(422, "A file path inside the ZIP is not allowed."),
    AdminErrorCode.ZIP_SYMLINK: ErrorSpec(
        422, "The ZIP file contains links, which are not allowed."
    ),
    AdminErrorCode.ZIP_RATIO_EXCEEDED: ErrorSpec(
        422, "A file in the ZIP expands too much when unpacked."
    ),
    AdminErrorCode.ZIP_UNCOMPRESSED_TOO_LARGE: ErrorSpec(
        422, "The ZIP file is too large when unpacked."
    ),
    AdminErrorCode.ZIP_NESTED_ARCHIVE: ErrorSpec(422, "ZIP files inside the ZIP are not allowed."),
    AdminErrorCode.ZIP_ENCRYPTED: ErrorSpec(422, "The ZIP file is password protected."),
    AdminErrorCode.ZIP_DUPLICATE_NAME: ErrorSpec(422, "Two files in the ZIP have the same name."),
    AdminErrorCode.ZIP_UNLISTED_FILE: ErrorSpec(
        422, "A file in the ZIP is not listed in the manifest."
    ),
    AdminErrorCode.MANIFEST_MISSING: ErrorSpec(422, "The ZIP file has no manifest.json."),
    AdminErrorCode.MANIFEST_INVALID: ErrorSpec(422, "The manifest could not be read."),
    AdminErrorCode.MANIFEST_VERSION_UNSUPPORTED: ErrorSpec(
        422, "This manifest version is not supported."
    ),
    AdminErrorCode.MANIFEST_TOO_LARGE: ErrorSpec(422, "The manifest is too large."),
    AdminErrorCode.MANIFEST_FILE_MISSING: ErrorSpec(
        422, "The manifest lists a file that is not in the ZIP."
    ),
    AdminErrorCode.DOCUMENT_NOT_REPLACEABLE: ErrorSpec(
        409, "Only a document that failed to process can have its file replaced."
    ),
    AdminErrorCode.DOCUMENT_NOT_RETRYABLE: ErrorSpec(
        409, "This document cannot be retried right now."
    ),
    AdminErrorCode.IDEMPOTENCY_KEY_REUSED: ErrorSpec(
        409, "This request was already used with different content. Start the upload again."
    ),
    AdminErrorCode.UPLOAD_BACKLOG_FULL: ErrorSpec(
        429, "Too many documents are being processed. Try again in a few minutes."
    ),
    AdminErrorCode.DAILY_UPLOAD_LIMIT: ErrorSpec(
        429, "The daily upload limit has been reached. Try again tomorrow."
    ),
    AdminErrorCode.UPLOADS_DISABLED: ErrorSpec(
        503, "Uploads are paused for now. You can still manage existing documents."
    ),
}


def admin_error(code: AdminErrorCode) -> tuple[int, str, str]:
    """``(status, code, message)`` ready for ``AppError``."""
    spec = ADMIN_ERRORS[code]
    return spec.status, code.value, spec.message


# --- Idempotency and import --------------------------------------------------------------------


class Operation(StrEnum):
    CREATE_DOCUMENT = "create_document"
    REPLACE_DOCUMENT = "replace_document"
    CONFIRM_IMPORT = "confirm_import"


IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_-]{8,128}$"
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


# --- Status stream (SSE, ING-07, ING-11) --------------------------------------------------------

SSE_EVENT_STATUS = "status"
SSE_EVENT_END = "end"
SSE_KEEPALIVE_COMMENT = ": keepalive"
# `event: status` carries ``DocumentProcessingStatus`` (apps/api admin schemas), built from the
# database on connect and on every change, so a reconnect needs no event ids or replay.
# `event: end` carries ``{"reason": "terminal" | "timeout"}``: "terminal" after ready or failed,
# "timeout" when the server closes a long stream and the client should reconnect.
SSE_END_REASONS: tuple[str, ...] = ("terminal", "timeout")
