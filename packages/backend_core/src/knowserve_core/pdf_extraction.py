"""PDF text extraction in a child process with a hard timeout (M3-02a, OPEN-31 D11, ADR 0010).

The parser (PyMuPDF4LLM, native code) never runs inside the caller. ``extract_pdf`` starts a fresh
Python interpreter, hands it the PDF bytes on stdin, waits at most ``timeout_seconds`` and reads a
JSON result from stdout. A hang is killed. A crash (segfault, out of memory, killed by the OS)
ends the child, not the caller. Either way the caller gets a ``PdfExtractionError`` that carries a
``FailureCode`` and so fails one attempt only.

This module imports no PDF library, so the API can import it without installing PyMuPDF. The
parser is imported only by ``_pdf_extract_child``, which exists only in the Worker image.

No document text is logged or put in an exception message (MON-05, SEC-18).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass

from .ingestion_contract import FAILURES, FailureCode

CHILD_MODULE = "knowserve_core._pdf_extract_child"
# Environment the child sees. The child parses hostile files, so it gets no secrets (database
# URL, API keys, tokens). SYSTEMROOT is needed by Python on Windows.
_CHILD_ENV_KEYS = ("PATH", "SYSTEMROOT", "LANG", "LC_ALL", "TMP", "TEMP", "TMPDIR")


@dataclass(frozen=True)
class ExtractedPage:
    """One page. ``number`` is 1-based. ``text`` has no NUL characters and no outer whitespace;
    it is empty for a page without selectable text (for example a scanned page)."""

    number: int
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    page_count: int
    pages: tuple[ExtractedPage, ...]


class PdfExtractionError(Exception):
    """Extraction failed. ``code`` is the stable ``FailureCode`` stored on the revision.
    ``retryable`` follows ``FAILURES`` (a timeout or a crash may succeed on another attempt; a
    corrupt or encrypted file cannot). ``detail`` is a short technical hint without document
    text."""

    def __init__(self, code: FailureCode, detail: str = "") -> None:
        super().__init__(f"{code.value}: {detail}" if detail else code.value)
        self.code = code
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return FAILURES[self.code].retryable


def _child_command(max_pages: int) -> list[str]:
    # -I: ignore PYTHON* variables and the user's site directory. The child imports the same
    # installed packages as the caller.
    return [sys.executable, "-I", "-m", CHILD_MODULE, str(max_pages)]


def _child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in _CHILD_ENV_KEYS if key in os.environ}
    env["PYTHONUTF8"] = "1"
    return env


def extract_pdf(data: bytes, *, timeout_seconds: float, max_pages: int) -> ExtractedDocument:
    """Extract the text of every page of ``data`` (a PDF) in a child process.

    ``timeout_seconds`` is ``Settings.pdf_extraction_timeout_seconds`` and ``max_pages`` is
    ``Settings.upload_max_pdf_pages``. Blocking: call it from a thread in async code (see
    ``extract_pdf_async``). Raises ``PdfExtractionError`` with one of:

    - ``INVALID_PDF`` (not openable, corrupt, empty, or unreasonably large text), terminal
    - ``PDF_ENCRYPTED`` (needs a password), terminal
    - ``TOO_MANY_PAGES`` (more than ``max_pages``), terminal
    - ``NO_EXTRACTABLE_TEXT`` (no page has any text, for example a scan), terminal
    - ``PROCESSING_TIMEOUT`` (the child was killed after ``timeout_seconds``), retryable
    - ``PROCESSING_CRASHED`` (the child died without a result), retryable
    - ``INTERNAL_ERROR`` (the child could not start or broke its protocol), retryable
    """
    try:
        proc = subprocess.Popen(
            _child_command(max_pages),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_child_env(),
        )
    except OSError as exc:
        raise PdfExtractionError(FailureCode.INTERNAL_ERROR, f"spawn failed: {exc.errno}") from exc

    try:
        stdout, _ = proc.communicate(data, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _kill(proc)
        raise PdfExtractionError(
            FailureCode.PROCESSING_TIMEOUT, f"no result after {timeout_seconds}s"
        ) from exc
    except BaseException:
        # Cancellation, KeyboardInterrupt: never leave the child running.
        _kill(proc)
        raise

    if proc.returncode != 0:
        raise PdfExtractionError(FailureCode.PROCESSING_CRASHED, f"exit code {proc.returncode}")
    return _parse_result(stdout)


async def extract_pdf_async(
    data: bytes, *, timeout_seconds: float, max_pages: int
) -> ExtractedDocument:
    """``extract_pdf`` in a worker thread, for async handlers. The thread waits for the child, so
    the event loop stays free. The hard timeout is enforced by ``extract_pdf``, not the loop."""
    return await asyncio.to_thread(
        extract_pdf, data, timeout_seconds=timeout_seconds, max_pages=max_pages
    )


def _kill(proc: subprocess.Popen[bytes]) -> None:
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate()  # reap the child and close the pipes
    except Exception:  # noqa: BLE001 - nothing useful to do; the child is already killed
        pass


def _parse_result(stdout: bytes) -> ExtractedDocument:
    try:
        result = json.loads(stdout)
        if not isinstance(result, dict):
            raise ValueError("result is not an object")
        if result.get("ok") is not True:
            code = FailureCode(result["code"])
            detail = str(result.get("detail", ""))[:200]
            raise PdfExtractionError(code, detail)
        page_count = result["page_count"]
        texts = result["pages"]
        if (
            not isinstance(page_count, int)
            or not isinstance(texts, list)
            or len(texts) != page_count
            or not all(isinstance(t, str) for t in texts)
        ):
            raise ValueError("malformed pages")
    except PdfExtractionError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise PdfExtractionError(
            FailureCode.INTERNAL_ERROR, f"bad child output: {type(exc).__name__}"
        ) from exc
    # The child already cleaned the text; this keeps the guarantee even if the child changes.
    pages = tuple(
        ExtractedPage(i + 1, text.replace("\x00", "").strip()) for i, text in enumerate(texts)
    )
    return ExtractedDocument(page_count=page_count, pages=pages)
