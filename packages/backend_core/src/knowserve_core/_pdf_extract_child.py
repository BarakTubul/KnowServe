"""Child process of ``pdf_extraction.extract_pdf``. Not an API: run it only through that module.

Protocol: argv[1] is the page limit, stdin is the PDF, stdout is one JSON object, either
``{"ok": true, "page_count": n, "pages": [text, ...]}`` or ``{"ok": false, "code": <FailureCode>,
"detail": <short hint>}``. Exit code 0 means the protocol was followed. Anything else (crash,
kill, out of memory) is a crash for the parent. Only this module imports the PDF libraries.
"""

from __future__ import annotations

import json
import os
import sys
from typing import cast

# A page of real text is a few thousand characters, so this is far above any legitimate 300-page
# document. It bounds what a hostile content stream can make the child send back.
MAX_TOTAL_CHARS = 10_000_000


def _fail(code: str, detail: str = "") -> dict[str, object]:
    return {"ok": False, "code": code, "detail": detail}


def extract(data: bytes, max_pages: int) -> dict[str, object]:
    # Imported here so a missing library is reported as a protocol failure, not an import crash,
    # and so importing this module (for tests) stays cheap.
    import pymupdf
    import pymupdf4llm

    if not data:
        return _fail("INVALID_PDF", "empty file")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError) as exc:
        return _fail("INVALID_PDF", type(exc).__name__)
    try:
        # A file that opens with the empty password (owner-password-only) is readable.
        if doc.needs_pass:
            return _fail("PDF_ENCRYPTED")
        page_count = doc.page_count
        if page_count < 1:
            return _fail("INVALID_PDF", "no pages")
        if page_count > max_pages:
            return _fail("TOO_MANY_PAGES", f"{page_count} pages")
        try:
            chunks = pymupdf4llm.to_markdown(
                doc, page_chunks=True, ignore_images=True, show_progress=False
            )
        except (pymupdf.FileDataError, RuntimeError) as exc:
            return _fail("INVALID_PDF", type(exc).__name__)
        if len(chunks) != page_count:
            return _fail("INTERNAL_ERROR", "page count mismatch")
        pages = [str(page["text"]).replace("\x00", "").strip() for page in cast(list, chunks)]
    finally:
        doc.close()
    if sum(len(text) for text in pages) > MAX_TOTAL_CHARS:
        return _fail("INVALID_PDF", "extracted text too large")
    # "Usable text" means at least one letter or digit, so a page of stray symbols or a scan
    # that only produced markup does not pass (ING-23).
    if not any(ch.isalnum() for text in pages for ch in text):
        return _fail("NO_EXTRACTABLE_TEXT")
    return {"ok": True, "page_count": page_count, "pages": pages}


def main() -> None:
    max_pages = int(sys.argv[1])
    data = sys.stdin.buffer.read()
    # Keep fd 1 for the result only. Libraries print banners to stdout, and native code writes
    # to fd 1 directly, so point fd 1 (and sys.stdout) at stderr while the parser runs.
    result_stream = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    try:
        result = extract(data, max_pages)
    except MemoryError:
        os._exit(137)  # a retryable crash for the parent, same as being killed for memory
    except Exception as exc:  # noqa: BLE001 - report any other bug as a failure, not a traceback
        result = _fail("INTERNAL_ERROR", type(exc).__name__)
    result_stream.write(json.dumps(result, ensure_ascii=True).encode("ascii"))
    result_stream.flush()


if __name__ == "__main__":
    main()
