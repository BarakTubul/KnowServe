"""Validation of untrusted upload input (SEC-11, ADM-10, M3-03).

Pure functions: nothing here touches the database or the object store, so a rejected request has
no side effects to undo. Every rejection is an ``AppError`` built from a stable ``AdminErrorCode``
(``admin_error``); the message never echoes client input.

What the API checks and what it leaves to the Worker:

* The API rejects what is plainly not an uploadable PDF: empty, oversize, a wrong signature or a
  truncated file (``NOT_A_PDF``), and hostile names and titles.
* Encrypted, image-only (no text) and over-page-limit PDFs pass these checks on purpose. The
  Worker opens the file with the real parser and fails the revision with ``PDF_ENCRYPTED``,
  ``NO_EXTRACTABLE_TEXT`` or ``TOO_MANY_PAGES``, which the Admin sees and can replace (plan
  M3-AC06, OPEN-17, ADM-18). The structural check below is a deliberately small stand-in for the
  M3-02a module; it is injected (``UploadService(pdf_check=...)``) so the real one replaces it
  without touching the routes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

from fastapi import UploadFile

from knowserve_core.ingestion_contract import AdminErrorCode, admin_error
from knowserve_core.web import AppError

MAX_TITLE_CHARS = 200
MAX_FILENAME_CHARS = 200
READ_CHUNK = 1024 * 1024

PdfCheck = Callable[[bytes], None]
"""Raises ``AppError(NOT_A_PDF)`` for a file that is not a structurally sound PDF."""

# Explicit bidirectional formatting characters (embeddings, overrides, isolates). They reorder how
# text is displayed, so a name can read differently from what it contains.
_BIDI_FORMATTING = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
# Marks that are harmless in a title (Hebrew text legitimately uses them) but not in a file name.
_BIDI_MARKS = frozenset("‎‏؜")
_LINE_SEPARATORS = frozenset("  \u0085")
_PDF_HEADER = re.compile(rb"%PDF-[12]\.\d")
_EOF_WINDOW = 2048


def reject(code: AdminErrorCode) -> AppError:
    return AppError(*admin_error(code))


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def _has_control(value: str) -> bool:
    return any(
        unicodedata.category(ch) == "Cc" or ch in _LINE_SEPARATORS or ch in _BIDI_FORMATTING
        for ch in value
    )


def validate_title(raw: str) -> str:
    """The normalized title, or ``TITLE_INVALID`` (1 to 200 characters, no control characters)."""
    title = normalize_text(raw)
    if not 1 <= len(title) <= MAX_TITLE_CHARS or _has_control(title):
        raise reject(AdminErrorCode.TITLE_INVALID)
    return title


def validate_filename(raw: str | None) -> str:
    """The sanitized file name label. It is stored for display only and never reaches a storage
    key (ADR 0010). Rejected: path separators (so ``../x.pdf``, ``/etc/x.pdf`` and ``C:\\x.pdf``
    all fail), control and bidirectional characters, over-long names (``INVALID_FILENAME``);
    anything that is not ``*.pdf`` (``NOT_A_PDF``)."""
    if raw is None:
        raise reject(AdminErrorCode.INVALID_FILENAME)
    name = normalize_text(raw)
    if not 1 <= len(name) <= MAX_FILENAME_CHARS:
        raise reject(AdminErrorCode.INVALID_FILENAME)
    if "/" in name or "\\" in name or _has_control(name):
        raise reject(AdminErrorCode.INVALID_FILENAME)
    for ch in name:
        if ch in _BIDI_MARKS or unicodedata.category(ch) in ("Cf", "Cs", "Co", "Cn"):
            raise reject(AdminErrorCode.INVALID_FILENAME)
    if not name.lower().endswith(".pdf"):
        raise reject(AdminErrorCode.NOT_A_PDF)
    if not name[:-4].strip(" ."):
        raise reject(AdminErrorCode.INVALID_FILENAME)
    return name


async def read_upload(file: UploadFile, max_bytes: int, too_large: AdminErrorCode) -> bytes:
    """Read the upload, never more than ``max_bytes`` plus one byte. The framework has already
    spooled the body; this bounds what the API keeps in memory."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(min(READ_CHUNK, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise reject(too_large)
        chunks.append(chunk)
    return b"".join(chunks)


def check_pdf_structure(data: bytes) -> None:
    """Minimal structural check: signature at offset 0, the end marker near the end, and the
    ``obj`` and ``startxref`` keywords. Raises ``NOT_A_PDF``. Not a parser: a file that passes can
    still be corrupt, which the Worker reports as ``INVALID_PDF``."""
    if not data:
        raise reject(AdminErrorCode.FILE_EMPTY)
    if _PDF_HEADER.match(data) is None:
        raise reject(AdminErrorCode.NOT_A_PDF)
    tail = data[-_EOF_WINDOW:]
    if b"%%EOF" not in tail or b"startxref" not in data[-_EOF_WINDOW * 2 :] or b" obj" not in data:
        raise reject(AdminErrorCode.NOT_A_PDF)


def validate_pdf(
    filename: str | None, data: bytes, pdf_check: PdfCheck = check_pdf_structure
) -> str:
    """Name, then content. Returns the sanitized file name."""
    name = validate_filename(filename)
    if not data:
        raise reject(AdminErrorCode.FILE_EMPTY)
    pdf_check(data)
    return name


MAX_ALLOWED_DEPARTMENTS = 50  # per document, in the create form and in manifest entries
