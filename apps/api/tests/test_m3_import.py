"""M3-04 tests: ZIP import preview and confirm (ADM-11 to ADM-14, SEC-11, M3-AC12 to AC14).

Hard gates: every hostile archive is rejected with its code and leaves no row, object or job;
preview creates nothing; confirmation re-validates, is idempotent and resumable; no access is
ever inferred from the owner.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from typing import Any

import pytest
from m3_upload_support import (
    ORIGIN,
    assert_nothing_created,
    counts,
    make_app,
    make_client,
    stored_keys,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_core.clock import FakeClock
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.qstash import FakePublisher
from knowserve_core.testing_fixtures import (
    HOSTILE_NAMES,
    make_pdf,
    make_zip,
    manifest_entry,
    manifest_json,
    pdf_image_only,
    pdf_two_pages,
    zip_bomb,
    zip_with_encrypted_flag,
    zip_with_symlink,
)

pytestmark = [pytest.mark.m3, pytest.mark.admin, pytest.mark.api, pytest.mark.integration]


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
async def admin(make_user: Any, make_session: Any) -> Any:
    return await make_session(await make_user("admin"))


def _client(engine: AsyncEngine, clock: FakeClock, store: Any, publisher: Any, **kw: Any):
    return make_client(make_app(engine, clock, store=store, publisher=publisher, **kw))


async def _post(client: Any, session: Any, path: str, data: bytes, key: str | None = None):
    headers = dict(session.headers)
    if key:
        headers["Idempotency-Key"] = key
    return await client.post(
        f"/v1/admin/imports/{path}",
        headers=headers,
        cookies=session.cookies,
        files={"file": ("import.zip", data, "application/zip")},
    )


def _good(n: int = 2, **entry: Any) -> bytes:
    files = {f"doc{i}.pdf": make_pdf([f"Document number {i}."]) for i in range(n)}
    return make_zip(files, manifest_json([manifest_entry(f, **entry) for f in files]))


def _zip_from(
    names_and_data: list[tuple[str, bytes]],
    manifest: bytes,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as z:
        for name, data in names_and_data:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.filename = name  # ZipInfo rewrites "\\" on Windows; keep the hostile name as is
            info.external_attr = 0o100644 << 16
            z.writestr(info, data, compress_type=compression)
        z.writestr("manifest.json", manifest)
    return buf.getvalue()


# --- ADM-12: preview is read only ------------------------------------------------------------


async def test_adm12_preview_lists_every_entry_and_creates_nothing(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    files = {"a.pdf": pdf_two_pages(), "b.pdf": pdf_two_pages(), "c.pdf": pdf_two_pages()}
    data = make_zip(
        files,
        manifest_json(
            [
                manifest_entry("a.pdf", allowed_departments=("finance", "legal")),
                manifest_entry("b.pdf", allowed_departments=("sales",)),
                manifest_entry("c.pdf", allowed_departments=None),  # only owner_department
            ]
        ),
    )
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", data)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["valid_count"], body["invalid_count"]) == (2, 1)
    assert [e["valid"] for e in body["entries"]] == [True, True, False]
    assert body["entries"][2]["error_code"] == "ALLOWED_DEPARTMENTS_MISSING"
    assert {d["slug"] for d in body["entries"][0]["allowed_departments"]} == {"finance", "legal"}
    await assert_nothing_created(engine, store)
    assert publisher.published == []


@pytest.mark.parametrize(
    ("entry", "code", "detail"),
    [
        ({"allowed_departments": None}, "ALLOWED_DEPARTMENTS_MISSING", None),
        ({"allowed_departments": ()}, "ALLOWED_DEPARTMENTS_EMPTY", None),
        ({"allowed_departments": ("finance", "atlantis")}, "UNKNOWN_DEPARTMENT", "atlantis"),
        ({"owner_department": "atlantis"}, "UNKNOWN_DEPARTMENT", "atlantis"),
        ({"title": "  "}, "TITLE_INVALID", None),
    ],
)
async def test_adm11_openl6_entry_department_rules_are_named_per_entry(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    entry: dict[str, Any],
    code: str,
    detail: str | None,
) -> None:
    data = _good(1, **entry)
    async with _client(engine, clock, store, publisher) as client:
        preview = await _post(client, admin, "preview", data)
        confirm = await _post(client, admin, "confirm", data, key="entry-rules-001")
    first = preview.json()["entries"][0]
    assert (first["valid"], first["error_code"], first["detail"]) == (False, code, detail)
    assert confirm.status_code == 200
    assert confirm.json()["results"][0]["status"] == "rejected"
    assert confirm.json()["results"][0]["error_code"] == code
    counted = await counts(engine)
    assert counted["documents"] == 0 and counted["jobs"] == 0 and stored_keys(store) == []


# --- SEC-11 / M3-AC12: hostile archives ------------------------------------------------------


def _hostile_archives() -> list[tuple[str, bytes, str]]:
    ok = pdf_two_pages()
    entry = lambda f: manifest_json([manifest_entry(f)])  # noqa: E731
    cases: list[tuple[str, bytes, str]] = [
        ("not-a-zip", b"this is not a zip" * 20, "ZIP_INVALID"),
        ("traversal", _zip_from([("../evil.pdf", ok)], entry("../evil.pdf")), "ZIP_UNSAFE_PATH"),
        ("deep-traversal", _zip_from([("a/../../e.pdf", ok)], entry("e.pdf")), "ZIP_UNSAFE_PATH"),
        ("absolute", _zip_from([("/etc/evil.pdf", ok)], entry("/etc/evil.pdf")), "ZIP_UNSAFE_PATH"),
        ("backslash", _zip_from([("a\\evil.pdf", ok)], entry("a\\evil.pdf")), "ZIP_UNSAFE_PATH"),
        ("drive", _zip_from([("C:evil.pdf", ok)], entry("C:evil.pdf")), "ZIP_UNSAFE_PATH"),
        ("symlink", zip_with_symlink(), "ZIP_SYMLINK"),
        ("encrypted", zip_with_encrypted_flag(), "ZIP_ENCRYPTED"),
        ("bomb", zip_bomb(), "ZIP_RATIO_EXCEEDED"),
        (
            "nested",
            _zip_from([("inner.zip", b"PK\x05\x06" + b"\0" * 18)], entry("inner.zip")),
            "ZIP_NESTED_ARCHIVE",
        ),
        ("duplicate", _dup_zip(ok), "ZIP_DUPLICATE_NAME"),
        (
            "case-duplicate",
            _zip_from([("A.pdf", ok), ("a.PDF", ok)], entry("A.pdf")),
            "ZIP_DUPLICATE_NAME",
        ),
        (
            "unlisted",
            _zip_from([("a.pdf", ok), ("extra.pdf", ok)], entry("a.pdf")),
            "ZIP_UNLISTED_FILE",
        ),
        ("no-manifest", make_zip({"a.pdf": ok}, None), "MANIFEST_MISSING"),
        ("bad-json", make_zip({"a.pdf": ok}, b"{not json"), "MANIFEST_INVALID"),
        ("nan", make_zip({"a.pdf": ok}, b'{"version": NaN, "documents": []}'), "MANIFEST_INVALID"),
        (
            "deep-json",
            _zip_from([("a.pdf", ok)], b"[" * 50000 + b"]" * 50000, zipfile.ZIP_STORED),
            "MANIFEST_INVALID",
        ),
        ("not-object", make_zip({"a.pdf": ok}, b"[]"), "MANIFEST_INVALID"),
        (
            "extra-key",
            make_zip({"a.pdf": ok}, b'{"version":1,"documents":[],"x":1}'),
            "MANIFEST_INVALID",
        ),
        (
            "version",
            make_zip({"a.pdf": ok}, manifest_json([manifest_entry("a.pdf")], version=2)),
            "MANIFEST_VERSION_UNSUPPORTED",
        ),
        (
            "file-listed-twice",
            make_zip({"a.pdf": ok}, manifest_json([manifest_entry("a.pdf")] * 2)),
            "MANIFEST_INVALID",
        ),
    ]
    return cases


def _dup_zip(ok: bytes) -> bytes:
    import warnings

    buf = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buf, "w") as z:
        warnings.simplefilter("ignore")
        z.writestr("a.pdf", ok)
        z.writestr("a.pdf", ok)
        z.writestr("manifest.json", manifest_json([manifest_entry("a.pdf")]))
    return buf.getvalue()


ARCHIVES = _hostile_archives()


@pytest.mark.parametrize(("case", "data", "code"), ARCHIVES, ids=[c[0] for c in ARCHIVES])
@pytest.mark.parametrize("route", ["preview", "confirm"])
async def test_sec11_hostile_archive_is_rejected_and_leaves_nothing(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    case: str,
    data: bytes,
    code: str,
    route: str,
) -> None:
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, route, data, key="hostile-key-0001")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code
    await assert_nothing_created(engine, store)
    assert publisher.published == []


async def test_sec11_too_many_files_total_size_and_zip_size(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    three = _good(3)
    big_files = {f"b{i}.pdf": make_pdf(["x" * 3000]) for i in range(2)}
    big_zip = make_zip(big_files, manifest_json([manifest_entry(f) for f in big_files]))
    async with _client(engine, clock, store, publisher, upload_max_zip_files=2) as client:
        many = await _post(client, admin, "preview", three)
    assert many.status_code == 422 and many.json()["error"]["code"] == "ZIP_TOO_MANY_FILES"
    async with _client(engine, clock, store, publisher, upload_max_zip_bytes=100) as client:
        big = await _post(client, admin, "preview", three)
    assert big.status_code == 413 and big.json()["error"]["code"] == "ZIP_TOO_LARGE"
    async with _client(
        engine,
        clock,
        store,
        publisher,
        upload_max_zip_uncompressed_bytes=5000,
        upload_max_zip_bytes=3000,
    ) as client:
        unpacked = await _post(client, admin, "preview", big_zip)
    assert unpacked.status_code == 422
    assert unpacked.json()["error"]["code"] == "ZIP_UNCOMPRESSED_TOO_LARGE"
    async with _client(engine, clock, store, publisher, upload_max_manifest_bytes=10) as client:
        manifest = await _post(client, admin, "preview", three)
    assert manifest.json()["error"]["code"] == "MANIFEST_TOO_LARGE"
    await assert_nothing_created(engine, store)


@pytest.mark.parametrize("name", HOSTILE_NAMES)
async def test_sec11_hostile_manifest_file_names_are_rejected(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    name: str,
) -> None:
    data = make_zip(
        {"ok.pdf": pdf_two_pages()},
        manifest_json([manifest_entry("ok.pdf"), manifest_entry(name)]),
    )
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", data)
    assert response.status_code == 200
    assert response.json()["entries"][0]["valid"] is True
    entry = response.json()["entries"][1]
    assert entry["valid"] is False
    assert entry["error_code"] in ("ZIP_UNSAFE_PATH", "MANIFEST_INVALID")


async def test_adm11_a_missing_or_non_pdf_member_invalidates_only_that_entry(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    data = make_zip(
        {"good.pdf": pdf_two_pages(), "fake.pdf": b"MZ not a pdf"},
        manifest_json(
            [manifest_entry("good.pdf"), manifest_entry("fake.pdf"), manifest_entry("gone.pdf")]
        ),
    )
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", data)
    codes = [e["error_code"] for e in response.json()["entries"]]
    assert codes == [None, "NOT_A_PDF", "MANIFEST_FILE_MISSING"]


# --- ADM-13, ADM-14: confirmation ------------------------------------------------------------


async def test_adm14_partial_success_then_a_retry_creates_exactly_one_more(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    files = {f"g{i}.pdf": make_pdf([f"Good {i}"]) for i in range(3)}
    entries = [manifest_entry(f, allowed_departments=("legal",)) for f in files]
    bad = manifest_entry("bad.pdf", allowed_departments=())
    data = make_zip({**files, "bad.pdf": pdf_two_pages()}, manifest_json([*entries, bad]))
    async with _client(engine, clock, store, publisher) as client:
        first = await _post(client, admin, "confirm", data, key="partial-key-0001")
        assert first.status_code == 200, first.text
        body = first.json()
        assert (body["created_count"], body["rejected_count"]) == (3, 1)
        assert [r["status"] for r in body["results"]] == ["created"] * 3 + ["rejected"]
        assert body["results"][3]["error_code"] == "ALLOWED_DEPARTMENTS_EMPTY"
        assert (await counts(engine))["documents"] == 3
        # The Admin fixes the file and sends only that entry again, with a new key.
        fixed = make_zip(
            {"bad.pdf": pdf_two_pages()},
            manifest_json([manifest_entry("bad.pdf", allowed_departments=("legal",))]),
        )
        retry = await _post(client, admin, "confirm", fixed, key="partial-key-0002")
    assert retry.json()["created_count"] == 1
    counted = await counts(engine)
    assert counted["documents"] == 4 and counted["jobs"] == 4 and len(stored_keys(store)) == 4
    access = await _rows(engine, "SELECT department_id FROM document_department_access")
    assert {str(a.department_id) for a in access} == {"3174db2f-1584-5ddb-8fbd-60b4157086d3"}


async def _rows(engine: AsyncEngine, sql: str) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql))).all())


async def test_adm13_confirming_twice_with_one_key_creates_one_set(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    data = _good(2)
    async with _client(engine, clock, store, publisher) as client:
        first = await _post(client, admin, "confirm", data, key="twice-key-00001")
        second = await _post(client, admin, "confirm", data, key="twice-key-00001")
        other = await _post(client, admin, "confirm", _good(3), key="twice-key-00001")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    counted = await counts(engine)
    assert counted["documents"] == 2 and counted["jobs"] == 2 and len(stored_keys(store)) == 2
    assert other.status_code == 409 and other.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_adm13_concurrent_confirms_with_one_key_create_each_entry_once(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    data = _good(3)
    async with _client(engine, clock, store, publisher) as client:
        responses = await asyncio.gather(
            *[_post(client, admin, "confirm", data, key="race-import-001") for _ in range(4)]
        )
    assert [r.status_code for r in responses] == [200] * 4, [r.text for r in responses]
    assert len({r.json()["results"][0]["document_id"] for r in responses}) == 1
    counted = await counts(engine)
    assert counted["documents"] == 3 and counted["import_batch_entries"] == 3
    assert counted["jobs"] == 3 and len(stored_keys(store)) == 3


async def test_adm14_a_half_finished_confirm_resumes_without_duplicating(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowserve_api.admin import imports as imports_module

    data = _good(3)
    real = imports_module._create_entry
    calls = {"n": 0}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("the process died before the third entry")
        return await real(*args, **kwargs)

    monkeypatch.setattr(imports_module, "_create_entry", flaky)
    async with _client(engine, clock, store, publisher) as client:
        died = await _post(client, admin, "confirm", data, key="resume-key-0001")
        assert died.status_code == 500
        assert (await counts(engine))["documents"] == 2
        monkeypatch.setattr(imports_module, "_create_entry", real)
        resumed = await _post(client, admin, "confirm", data, key="resume-key-0001")
    assert resumed.status_code == 200
    assert resumed.json()["created_count"] == 3
    counted = await counts(engine)
    assert counted["documents"] == 3 and counted["import_batch_entries"] == 3
    assert len(stored_keys(store)) == 3


async def test_adm11_a_tampered_confirmation_cannot_import_an_invalid_entry(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    """The client never says which entries are valid: confirmation validates the ZIP itself."""
    data = make_zip(
        {"a.pdf": pdf_two_pages(), "scan.pdf": pdf_image_only()[:100]},
        manifest_json(
            [manifest_entry("a.pdf"), manifest_entry("scan.pdf", allowed_departments=None)]
        ),
    )
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "confirm", data, key="tamper-key-0001")
    assert [r["status"] for r in response.json()["results"]] == ["created", "rejected"]
    assert (await counts(engine))["documents"] == 1 and len(stored_keys(store)) == 1


async def test_d1_a_batch_over_the_in_flight_limit_is_refused_before_anything_is_created(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with _client(engine, clock, store, publisher, upload_max_in_flight=2) as client:
        response = await _post(client, admin, "confirm", _good(3), key="backlog-key-001")
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "UPLOAD_BACKLOG_FULL"
    await assert_nothing_created(engine, store)


async def test_adm17_confirmation_is_audited_without_file_content(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with _client(engine, clock, store, publisher) as client:
        await _post(client, admin, "confirm", _good(2), key="audit-key-00001")
    rows = await _rows(
        engine,
        "SELECT event, details::text AS d FROM audit_events WHERE event LIKE 'admin.%' ORDER BY id",
    )
    events = [r.event for r in rows]
    assert (
        events.count("admin.document.created") == 2 and events.count("admin.import.confirmed") == 1
    )
    assert all("Document number" not in r.d and ".pdf" not in r.d for r in rows)


async def test_m3_ac26_disabled_uploads_block_import(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with _client(engine, clock, store, publisher, uploads_enabled=False) as client:
        for route in ("preview", "confirm"):
            response = await _post(client, admin, route, _good(1), key="off-key-0000001")
            assert response.status_code == 503
    await assert_nothing_created(engine, store)
    assert ORIGIN
