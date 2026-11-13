"""M3-01 tests: ObjectStore.delete, ingestion contract catalogs, embedding provider, config
guards and fixture builders. No database needed.
"""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import httpx
import pytest

from conftest import sign_qstash_delivery
from knowserve_core.embeddings import (
    EmbeddingError,
    FakeEmbeddingProvider,
    build_embedding_provider,
)
from knowserve_core.ingestion_contract import (
    ADMIN_ERRORS,
    EMBEDDING_DIMENSIONS,
    FAILURES,
    AdminErrorCode,
    FailureCode,
    admin_error,
    build_index_identity,
    failure_message,
)
from knowserve_core.object_store import (
    FakeObjectStore,
    FilesystemObjectStore,
    ObjectNotFound,
    ObjectStoreError,
    R2ObjectStore,
)
from knowserve_core.qstash import SignatureError, verify_signature
from knowserve_core.settings import Settings
from knowserve_core.testing_fixtures import (
    HOSTILE_NAMES,
    make_pdf,
    make_zip,
    manifest_entry,
    manifest_json,
    pdf_corrupt,
    pdf_encrypted,
    pdf_image_only,
    pdf_many_pages,
    pdf_two_pages,
    pdf_with_nul_in_text,
    zip_bomb,
    zip_with_encrypted_flag,
    zip_with_symlink,
)

pytestmark = [pytest.mark.m3]


def _settings(**kw: object) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql://u:p@localhost/db",
        **kw,
    )


# --- ObjectStore.delete (ARCH-14, M3-AC03) ---


async def _drain(store: FakeObjectStore | FilesystemObjectStore, key: str) -> bytes:
    return b"".join([chunk async for chunk in store.stream(key)])


@pytest.mark.parametrize("kind", ["fake", "filesystem"])
async def test_m3_arch14_delete_removes_an_object_and_is_idempotent(
    kind: str, tmp_path: Path
) -> None:
    store: FakeObjectStore | FilesystemObjectStore = (
        FakeObjectStore() if kind == "fake" else FilesystemObjectStore(tmp_path)
    )
    await store.put("documents/a/b.pdf", b"bytes", "application/pdf")
    assert await _drain(store, "documents/a/b.pdf") == b"bytes"
    await store.delete("documents/a/b.pdf")
    with pytest.raises(ObjectNotFound):
        await store.size("documents/a/b.pdf")
    await store.delete("documents/a/b.pdf")  # a missing key is not an error
    await store.delete("../outside.pdf")  # a key that escapes the root is not an error either


async def test_m3_arch14_filesystem_delete_cannot_leave_the_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    root = tmp_path / "root"
    root.mkdir()
    store = FilesystemObjectStore(root)
    await store.delete("../outside.txt")
    assert outside.read_text() == "keep"


def _r2(handler: httpx.MockTransport) -> R2ObjectStore:
    return R2ObjectStore(
        endpoint="https://acct123.r2.cloudflarestorage.com",
        bucket="docs-bucket",
        access_key_id="AKIAEXAMPLEKEYID",
        secret_access_key="super-secret-access-key-value",
        client=httpx.AsyncClient(transport=handler),
    )


@pytest.mark.parametrize("status", [200, 204, 404])
async def test_m3_arch14_r2_delete_sends_a_signed_delete_and_accepts_missing_keys(
    status: int,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    await _r2(httpx.MockTransport(handler)).delete("documents/a/b.pdf")
    assert [r.method for r in seen] == ["DELETE"]
    assert seen[0].url.path == "/docs-bucket/documents/a/b.pdf"
    assert seen[0].headers["authorization"].startswith("AWS4-HMAC-SHA256 ")


async def test_m3_arch14_r2_delete_failure_is_an_error_without_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with pytest.raises(ObjectStoreError) as caught:
        await _r2(httpx.MockTransport(handler)).delete("documents/a/b.pdf")
    text = str(caught.value)
    assert "403" in text
    assert "super-secret" not in text and "r2.cloudflarestorage" not in text


# --- Catalogs ---


def test_m3_every_admin_error_code_has_a_status_and_a_friendly_message() -> None:
    assert set(ADMIN_ERRORS) == set(AdminErrorCode)
    for code in AdminErrorCode:
        status, name, message = admin_error(code)
        assert name == code.value
        assert status in (404, 409, 413, 422, 429, 503)
        # PROD-13: friendly and non-technical.
        assert message and message.endswith(".")
        assert not any(w in message.lower() for w in ("exception", "traceback", "null", "http"))


def test_m3_contract_statuses_match_the_plan() -> None:
    assert ADMIN_ERRORS[AdminErrorCode.FILE_TOO_LARGE].status == 413
    assert ADMIN_ERRORS[AdminErrorCode.UPLOADS_DISABLED].status == 503
    assert ADMIN_ERRORS[AdminErrorCode.UPLOAD_BACKLOG_FULL].status == 429
    assert ADMIN_ERRORS[AdminErrorCode.DOCUMENT_NOT_REPLACEABLE].status == 409
    assert ADMIN_ERRORS[AdminErrorCode.ALLOWED_DEPARTMENTS_EMPTY].status == 422


def test_m3_ing23_failure_codes_split_into_terminal_and_retryable() -> None:
    assert set(FAILURES) == set(FailureCode)
    terminal = {c for c, spec in FAILURES.items() if not spec.retryable}
    assert terminal == {
        FailureCode.NO_EXTRACTABLE_TEXT,
        FailureCode.INVALID_PDF,
        FailureCode.PDF_ENCRYPTED,
        FailureCode.TOO_MANY_PAGES,
        FailureCode.DOCUMENT_DELETED,
    }
    assert failure_message(None) is None
    assert (
        failure_message("NO_EXTRACTABLE_TEXT") == FAILURES[FailureCode.NO_EXTRACTABLE_TEXT].message
    )
    assert failure_message("SOMETHING_NEW") == FAILURES[FailureCode.INTERNAL_ERROR].message


def test_m3_ing18_index_identity_changes_with_every_input() -> None:
    base = build_index_identity("text-embedding-3-small", 1536, 512, 64)
    assert base == "text-embedding-3-small:1536:c512o64"
    assert build_index_identity("other", 1536, 512, 64) != base
    assert build_index_identity("text-embedding-3-small", 1536, 256, 64) != base
    assert build_index_identity("text-embedding-3-small", 1536, 512, 32) != base


# --- Embedding provider ---


async def test_m3_ing17_fake_embeddings_are_deterministic_unit_vectors_of_contract_width() -> None:
    fake = FakeEmbeddingProvider()
    a1, b1 = await fake.embed(["alpha", "beta"])
    a2 = (await FakeEmbeddingProvider().embed(["alpha"]))[0]
    assert a1 == a2 and a1 != b1
    assert len(a1) == EMBEDDING_DIMENSIONS
    assert abs(sum(v * v for v in a1) - 1.0) < 1e-6


async def test_m3_ing16_fake_embedding_failure_raises_without_partial_results() -> None:
    fake = FakeEmbeddingProvider(fail_after=2)
    await fake.embed(["first call works"])
    with pytest.raises(EmbeddingError):
        await fake.embed(["second call fails"])


def test_m3_fake_embeddings_are_refused_in_production() -> None:
    kwargs = {"model": "m", "dimensions": EMBEDDING_DIMENSIONS}
    assert isinstance(build_embedding_provider("fake", "local", **kwargs), FakeEmbeddingProvider)
    with pytest.raises(RuntimeError, match="not allowed in production"):
        build_embedding_provider("fake", "production", **kwargs)
    with pytest.raises(RuntimeError, match="KS_OPENAI_API_KEY"):
        build_embedding_provider("openai", "production", **kwargs)


# --- Config ---


def test_m3_open31_d1_defaults_are_the_approved_limits() -> None:
    s = _settings()
    assert s.uploads_enabled is True
    assert s.upload_max_pdf_bytes == 20 * 1024 * 1024
    assert s.upload_max_pdf_pages == 300
    assert s.upload_max_zip_bytes == 25 * 1024 * 1024
    assert s.upload_max_zip_files == 20
    assert s.upload_max_zip_uncompressed_bytes == 100 * 1024 * 1024
    assert s.upload_max_zip_ratio == 20
    assert s.upload_max_manifest_bytes == 256 * 1024
    assert s.upload_max_in_flight == 10
    assert s.upload_max_per_day == 50
    assert (s.chunk_size_tokens, s.chunk_overlap_tokens) == (512, 64)
    assert (s.embedding_model, s.embedding_dimensions) == ("text-embedding-3-small", 1536)


def test_m3_config_guards_reject_inconsistent_values_and_fake_embeddings_in_production() -> None:
    with pytest.raises(ValueError, match="OVERLAP"):
        _settings(chunk_size_tokens=64, chunk_overlap_tokens=64)
    with pytest.raises(ValueError, match="DIMENSIONS"):
        _settings(embedding_dimensions=768)
    with pytest.raises(ValueError, match="ZIP_BYTES"):
        _settings(upload_max_zip_bytes=10, upload_max_zip_uncompressed_bytes=5)
    prod = {"env": "production", "api_allowed_origins": ["https://app.example"]}
    with pytest.raises(ValueError, match="EMBEDDING_PROVIDER=fake"):
        _settings(embedding_provider="fake", **prod)
    # The API and the deployed M2 configuration need no OpenAI key to start.
    assert _settings(**prod).embedding_provider == "openai"


# --- Fixtures ---


def test_m3_fixture_pdfs_are_deterministic_and_have_the_expected_shape() -> None:
    assert pdf_two_pages() == pdf_two_pages()
    assert pdf_two_pages().startswith(b"%PDF-")
    assert b"/Count 2" in pdf_two_pages()
    assert b"/Count 40" in pdf_many_pages(40)
    assert b"/Encrypt" in pdf_encrypted() and b"/Encrypt" not in pdf_two_pages()
    assert b"BT" not in pdf_image_only() and b"BI" in pdf_image_only()
    assert b"\\000" in pdf_with_nul_in_text()
    assert pdf_corrupt().startswith(b"%PDF-") and b"xref" not in pdf_corrupt()
    with pytest.raises(ValueError):
        make_pdf([])


def test_m3_fixture_zips_cover_each_hostile_shape() -> None:
    good = make_zip({"a.pdf": pdf_two_pages()}, manifest_json([manifest_entry("a.pdf")]))
    names = zipfile.ZipFile(BytesIO(good)).namelist()
    assert names == ["a.pdf", "manifest.json"]
    for name in HOSTILE_NAMES:
        archive = zipfile.ZipFile(BytesIO(make_zip({name: b"x"}, manifest_json([]))))
        assert any(n for n in archive.namelist() if n != "manifest.json")
    link = zipfile.ZipFile(BytesIO(zip_with_symlink())).infolist()[0]
    assert (link.external_attr >> 16) & 0o170000 == 0o120000
    bomb = zipfile.ZipFile(BytesIO(zip_bomb())).infolist()[0]
    assert bomb.file_size / max(bomb.compress_size, 1) > 100
    flagged = zipfile.ZipFile(BytesIO(zip_with_encrypted_flag())).infolist()[0]
    assert flagged.flag_bits & 0x1
    no_manifest = zipfile.ZipFile(BytesIO(make_zip({"a.pdf": b"x"}))).namelist()
    assert "manifest.json" not in no_manifest
    assert manifest_entry("a.pdf", allowed_departments=None).get("allowed_departments") is None


def test_m3_sec14_signed_delivery_helper_matches_the_real_verifier() -> None:
    url = "https://worker.test/internal/jobs/run"
    key = "local-only-qstash-current-key-not-a-secret"
    body = b'{"schema_version":1,"job_id":"x"}'
    token = sign_qstash_delivery(body, key, url)
    verify_signature(token=token, body=body, signing_keys=[key], expected_url=url)
    for bad in (
        sign_qstash_delivery(body, "another-local-only-key-not-a-secret-000", url),
        sign_qstash_delivery(body, key, url, exp=int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())),
        sign_qstash_delivery(body, key, "https://elsewhere.test/internal/jobs/run"),
        sign_qstash_delivery(b"{}", key, url),
        sign_qstash_delivery(body, key, url, iss="Someone"),
    ):
        with pytest.raises(SignatureError):
            verify_signature(token=bad, body=body, signing_keys=[key], expected_url=url)
