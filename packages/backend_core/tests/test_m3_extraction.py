"""M3-02a tests: PDF extraction in a child process and page-bound chunking.

The SEC-11 extraction matrix is a hard gate: no skips, no xfails. Requirement ids are in the test
names (TEST-07). The real PyMuPDF4LLM runs on the fixture PDFs; only the hang and crash tests swap
the child command for a tiny script. No database and no network.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from knowserve_core import chunking, pdf_extraction
from knowserve_core.chunking import Chunk, chunk_pages, count_tokens, split_sentences
from knowserve_core.ingestion_contract import FAILURES, FailureCode
from knowserve_core.pdf_extraction import (
    ExtractedPage,
    PdfExtractionError,
    extract_pdf,
    extract_pdf_async,
)
from knowserve_core.testing_fixtures import (
    make_pdf,
    not_a_pdf,
    pdf_corrupt,
    pdf_encrypted,
    pdf_image_only,
    pdf_many_pages,
    pdf_two_pages,
    pdf_with_nul_in_text,
)

pytestmark = pytest.mark.m3

TIMEOUT = 30
MAX_PAGES = 300
REPO_ROOT = Path(__file__).resolve().parents[3]


def _extract(data: bytes, *, max_pages: int = MAX_PAGES, timeout: float = TIMEOUT):
    return extract_pdf(data, timeout_seconds=timeout, max_pages=max_pages)


def _use_child(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    """Replace the extraction child with ``python -c code`` (stdin is still the PDF)."""
    monkeypatch.setattr(
        pdf_extraction, "_child_command", lambda max_pages: [sys.executable, "-I", "-c", code]
    )


# --- Extraction: results ---------------------------------------------------------------------


def test_ing02_extract_returns_text_per_page_with_one_based_numbers() -> None:
    doc = _extract(pdf_two_pages())
    assert doc.page_count == 2
    assert [p.number for p in doc.pages] == [1, 2]
    assert "Employees receive twenty days" in doc.pages[0].text
    assert "Expenses are reimbursed" in doc.pages[1].text


def test_ing02_mixed_pdf_keeps_empty_pages_so_numbers_stay_aligned() -> None:
    doc = _extract(make_pdf(["First page text.", None, "Third page text."]))
    assert [p.number for p in doc.pages] == [1, 2, 3]
    assert doc.pages[1].text == ""
    assert "Third page text" in doc.pages[2].text


def test_sec11_extract_strips_nul_bytes_end_to_end() -> None:
    doc = _extract(pdf_with_nul_in_text())
    text = doc.pages[0].text
    assert "\x00" not in text
    assert "before" in text and "after" in text


def test_sec11_extract_strips_nul_bytes_from_any_child_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code = (
        "import json,sys;sys.stdin.buffer.read();"
        "print(json.dumps({'ok':True,'page_count':2,'pages':['a\\u0000b\\u0000 ','\\u0000']}))"
    )
    _use_child(monkeypatch, code)
    doc = _extract(b"%PDF-1.4")
    assert [p.text for p in doc.pages] == ["ab", ""]


def test_ing02_real_seed_documents_extract_and_chunk() -> None:
    seed_dir = REPO_ROOT / "apps" / "api" / "src" / "knowserve_api" / "seed" / "data"
    files = sorted(seed_dir.glob("*.pdf"))
    assert len(files) == 4
    for path in files:
        doc = _extract(path.read_bytes())
        assert doc.page_count >= 1
        chunks = chunk_pages(doc.pages, chunk_size_tokens=512, chunk_overlap_tokens=64)
        assert chunks, path.name
        assert all(1 <= c.page_number <= doc.page_count for c in chunks)


async def test_ing02_extract_async_matches_sync() -> None:
    data = pdf_two_pages()
    assert await extract_pdf_async(data, timeout_seconds=TIMEOUT, max_pages=MAX_PAGES) == _extract(
        data
    )


# --- Extraction: failure codes (SEC-11, ING-09, ING-23) ---------------------------------------


def _code(data: bytes, **kwargs) -> PdfExtractionError:
    with pytest.raises(PdfExtractionError) as info:
        _extract(data, **kwargs)
    return info.value


def test_ing23_image_only_pdf_is_no_extractable_text_and_not_retryable() -> None:
    err = _code(pdf_image_only())
    assert err.code is FailureCode.NO_EXTRACTABLE_TEXT
    assert err.retryable is False


def test_sec11_encrypted_pdf_is_pdf_encrypted() -> None:
    err = _code(pdf_encrypted())
    assert err.code is FailureCode.PDF_ENCRYPTED
    assert err.retryable is False


@pytest.mark.parametrize(
    "data",
    [pdf_corrupt(), not_a_pdf(), b"", b"%PDF-1.4\n"],
    ids=["corrupt", "zip", "empty", "stub"],
)
def test_sec11_unreadable_files_are_invalid_pdf(data: bytes) -> None:
    err = _code(data)
    assert err.code is FailureCode.INVALID_PDF
    assert err.retryable is False


def test_sec11_page_limit_is_enforced_by_the_child() -> None:
    data = pdf_many_pages(5)
    assert _code(data, max_pages=4).code is FailureCode.TOO_MANY_PAGES
    assert _extract(data, max_pages=5).page_count == 5  # exactly at the limit is fine


def test_sec11_failure_messages_contain_no_document_text() -> None:
    err = _code(pdf_encrypted())
    assert "Secret" not in str(err) and "Secret" not in err.detail


# --- Extraction: timeout, crash, hostile child output (D11) ------------------------------------


def test_sec11_timeout_kills_the_child_and_fails_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_child(monkeypatch, "import time; time.sleep(120)")
    started: list[subprocess.Popen[Any]] = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(pdf_extraction.subprocess, "Popen", spy)
    t0 = time.monotonic()
    with pytest.raises(PdfExtractionError) as info:
        extract_pdf(pdf_two_pages(), timeout_seconds=1, max_pages=MAX_PAGES)
    assert time.monotonic() - t0 < 20
    assert info.value.code is FailureCode.PROCESSING_TIMEOUT
    assert info.value.retryable is FAILURES[FailureCode.PROCESSING_TIMEOUT].retryable is True
    assert len(started) == 1
    assert started[0].poll() is not None, "the child must be dead and reaped"


@pytest.mark.parametrize(
    "code",
    [
        "import ctypes; ctypes.string_at(0)",  # native crash (segfault / access violation)
        "import os; os._exit(137)",  # killed, as for out of memory
        "import sys; sys.exit(3)",
    ],
    ids=["segfault", "killed", "nonzero-exit"],
)
def test_sec11_child_crash_is_isolated_from_the_caller(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(
            pdf_extraction, "_child_command", lambda n: [sys.executable, "-I", "-c", code]
        )
        with pytest.raises(PdfExtractionError) as info:
            _extract(pdf_two_pages())
    assert info.value.code is FailureCode.PROCESSING_CRASHED
    assert info.value.retryable is True
    # The caller is unharmed: the next extraction with the real child works.
    assert _extract(pdf_two_pages()).page_count == 2


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        "[]",
        '{"ok": true, "page_count": 2, "pages": ["only one"]}',
        '{"ok": true, "page_count": 1, "pages": [1]}',
        '{"ok": false, "code": "NOT_A_REAL_CODE"}',
        "",
    ],
    ids=["garbage", "list", "count-mismatch", "non-string", "unknown-code", "empty"],
)
def test_sec11_bad_child_output_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    _use_child(monkeypatch, f"import sys; sys.stdin.buffer.read(); sys.stdout.write({stdout!r})")
    err = _code(b"%PDF-1.4")
    assert err.code is FailureCode.INTERNAL_ERROR
    assert err.retryable is True


def test_sec14_child_gets_no_secrets_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KS_OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("KS_DATABASE_URL", "postgresql://u:p@h/db")
    code = (
        "import json,os,sys; sys.stdin.buffer.read();"
        "print(json.dumps({'ok':True,'page_count':1,'pages':[' '.join(sorted(os.environ))]}))"
    )
    _use_child(monkeypatch, code)
    seen = _extract(b"%PDF-1.4").pages[0].text
    assert "KS_" not in seen
    assert "PATH" in seen.upper()


def test_sec11_child_stdout_noise_does_not_break_the_result() -> None:
    # PyMuPDF4LLM prints a banner on import; the real fixtures only pass if fd 1 is protected.
    # This asserts the property directly on the child module.
    proc = subprocess.run(
        [sys.executable, "-I", "-m", pdf_extraction.CHILD_MODULE, "10"],
        input=pdf_two_pages(),
        capture_output=True,
        timeout=60,
        check=True,
    )
    assert proc.stdout.startswith(b'{"ok": true')
    assert proc.stdout.count(b"\n") == 0


# --- Chunking ------------------------------------------------------------------------------------


def _sentence(tag: str, i: int) -> str:
    return f"{tag} sentence number {i} explains the leave policy for employees in detail. "


def _page(number: int, tag: str, sentences: int) -> ExtractedPage:
    return ExtractedPage(number, "".join(_sentence(tag, i) for i in range(sentences)).strip())


def test_ing02_no_chunk_spans_a_page_and_pages_are_kept() -> None:
    pages = [_page(1, "alpha", 80), _page(2, "bravo", 80), _page(3, "charlie", 80)]
    chunks = chunk_pages(pages, chunk_size_tokens=512, chunk_overlap_tokens=64)
    tags = {1: "alpha", 2: "bravo", 3: "charlie"}
    assert {c.page_number for c in chunks} == {1, 2, 3}
    for chunk in chunks:
        others = [t for n, t in tags.items() if n != chunk.page_number]
        assert tags[chunk.page_number] in chunk.text
        assert not any(t in chunk.text for t in others), "a chunk crossed a page boundary"
    # Page order is preserved.
    assert [c.page_number for c in chunks] == sorted(c.page_number for c in chunks)


def test_ing02_ordinals_are_zero_based_contiguous_and_tokens_are_positive() -> None:
    pages = [_page(1, "alpha", 60), ExtractedPage(2, ""), _page(3, "bravo", 5), _page(4, "c", 1)]
    chunks = chunk_pages(pages, chunk_size_tokens=512, chunk_overlap_tokens=64)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert chunks and all(c.token_count >= 1 for c in chunks)
    assert 2 not in {c.page_number for c in chunks}, "an empty page makes no chunk"


def test_ing02_chunk_size_is_respected_and_token_count_is_exact() -> None:
    chunks = chunk_pages([_page(1, "alpha", 200)], chunk_size_tokens=128, chunk_overlap_tokens=16)
    assert len(chunks) > 3
    for chunk in chunks:
        assert chunk.token_count == count_tokens(chunk.text)
        assert chunk.token_count <= 128


def test_ing02_consecutive_chunks_on_a_page_overlap() -> None:
    chunks = chunk_pages([_page(1, "alpha", 200)], chunk_size_tokens=128, chunk_overlap_tokens=48)
    assert len(chunks) > 2
    for before, after in zip(chunks, chunks[1:], strict=False):
        last_sentence = split_sentences(before.text)[-1].strip()
        assert last_sentence in after.text


def test_ing02_chunking_is_deterministic() -> None:
    pages = [_page(1, "alpha", 90), _page(2, "bravo", 40)]
    first = chunk_pages(pages, chunk_size_tokens=512, chunk_overlap_tokens=64)
    second = chunk_pages(pages, chunk_size_tokens=512, chunk_overlap_tokens=64)
    assert first == second
    assert all(isinstance(c, Chunk) for c in first)


def test_ing02_extraction_then_chunking_is_deterministic_on_a_fixture() -> None:
    data = make_pdf([f"Page {i} " + "policy text. " * 40 for i in range(1, 4)])
    runs = [
        chunk_pages(_extract(data).pages, chunk_size_tokens=16, chunk_overlap_tokens=4)
        for _ in range(2)
    ]
    assert runs[0] == runs[1] and len(runs[0]) > 3


def test_ing02_a_single_unbroken_token_run_still_respects_the_size() -> None:
    # No spaces or sentence ends: the splitter must fall back to smaller pieces.
    chunks = chunk_pages(
        [ExtractedPage(1, "x" * 30_000)], chunk_size_tokens=512, chunk_overlap_tokens=64
    )
    assert len(chunks) >= 1
    assert all(1 <= c.token_count <= 512 for c in chunks)


def test_sec12_special_token_lookalikes_in_text_do_not_break_chunking() -> None:
    text = "Ignore previous text <|endoftext|> and <|fim_prefix|> more. Next sentence here."
    chunks = chunk_pages([ExtractedPage(1, text)], chunk_size_tokens=512, chunk_overlap_tokens=64)
    assert chunks and "<|endoftext|>" in chunks[0].text
    assert chunks[0].token_count == count_tokens(chunks[0].text)


def test_ing02_split_sentences_is_lossless() -> None:
    text = 'One. Two!  Three? "Quoted." (Paren.) tail without end\n\nNext paragraph. שלום עולם. End'
    pieces = split_sentences(text)
    assert "".join(pieces) == text
    assert len(pieces) >= 6


def test_ing02_overlap_not_below_size_is_refused() -> None:
    with pytest.raises(ValueError):
        chunk_pages([_page(1, "a", 3)], chunk_size_tokens=64, chunk_overlap_tokens=64)


# --- Offline tokenizer (F17) ---------------------------------------------------------------------


def test_f17_chunking_needs_no_network_and_no_download() -> None:
    """In a fresh interpreter every socket connection raises and the tiktoken cache is empty.
    Importing LlamaIndex, building the tokenizer and chunking must still work."""
    script = """
import os, socket, sys, tempfile

def blocked(*args, **kwargs):
    raise RuntimeError("network access attempted")

socket.socket.connect = blocked
socket.create_connection = blocked
socket.getaddrinfo = blocked
os.environ["TIKTOKEN_CACHE_DIR"] = tempfile.mkdtemp()
os.environ["DATA_GYM_CACHE_DIR"] = tempfile.mkdtemp()
os.environ["NLTK_DATA"] = tempfile.mkdtemp()

from knowserve_core.chunking import chunk_pages
from knowserve_core.pdf_extraction import ExtractedPage

text = "Employees receive twenty days of leave. Requests go to the manager. " * 120
chunks = chunk_pages([ExtractedPage(1, text)], chunk_size_tokens=512, chunk_overlap_tokens=64)
assert len(chunks) > 1 and all(c.token_count <= 512 for c in chunks)
print("offline-ok")
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "offline-ok" in proc.stdout


def test_f17_bundled_vocabulary_matches_its_published_hash() -> None:
    import hashlib

    raw = chunking._VOCAB_FILE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == chunking._VOCAB_SHA256


def test_f17_corrupt_vocabulary_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bad = tmp_path / "cl100k_base.tiktoken"
    bad.write_bytes(b"IQ== 0\n")
    chunking.get_encoding.cache_clear()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(chunking, "_VOCAB_FILE", bad)
            with pytest.raises(RuntimeError):
                chunking.get_encoding()
        assert chunking.get_encoding() is not None  # the real file loads again
    finally:
        chunking.get_encoding.cache_clear()
