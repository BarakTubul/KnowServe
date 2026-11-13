"""M3-03 tests: the single upload route and the creation service.

Hard gates (no skips, no xfails): atomicity with fault injection (M3-AC03), the SEC-11 matrix for
hostile uploads (M3-AC11) that asserts no row, object or job afterwards, no inferred access
(ADM-05, OPEN-16), server-generated storage keys, mass-assignment rejection, the uploads switch
(M3-AC26), idempotent replay and concurrency (ADM-13), the upload limits (OPEN-31 D1) and audit
and log hygiene (MON-05, SEC-18). The authorization and CSRF walk of every admin route, multipart
ones included, is `test_m3_admin_contract.py`.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import pytest
from m3_upload_support import (
    ENG,
    FIN,
    HR,
    LEGAL,
    assert_nothing_created,
    counts,
    make_app,
    make_client,
    post_document,
    stored_keys,
    upload_data,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from knowserve_core.clock import FakeClock
from knowserve_core.object_store import FakeObjectStore, ObjectStoreError
from knowserve_core.qstash import FakePublisher
from knowserve_core.testing_fixtures import (
    HOSTILE_NAMES,
    make_pdf,
    not_a_pdf,
    pdf_corrupt,
    pdf_encrypted,
    pdf_image_only,
    pdf_two_pages,
)

pytestmark = [pytest.mark.m3, pytest.mark.admin, pytest.mark.api, pytest.mark.integration]

KEY_RE = re.compile(r"^documents/[0-9a-f-]{36}/[0-9a-f-]{36}\.pdf$")


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
async def admin(make_user: Any, make_session: Any) -> Any:
    return await make_session(await make_user("admin"))


async def _client(engine: AsyncEngine, clock: FakeClock, store: Any, publisher: Any, **kw: Any):
    return make_client(make_app(engine, clock, store=store, publisher=publisher, **kw))


async def _rows(engine: AsyncEngine, sql: str, **params: Any) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


# --- ADM-03: the happy path --------------------------------------------------------------------


async def test_adm03_upload_creates_everything_in_one_go(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher) as client:
        pdf = pdf_two_pages()
        response = await post_document(
            client, admin, pdf=pdf, data=upload_data(title="  Leave policy  ", allowed=(HR, FIN))
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued" and body["phase"] is None
    assert body["title"] == "Leave policy" and body["filename"] == "policy.pdf"
    assert body["size_bytes"] == len(pdf) and body["can_retry"] is False
    assert body["owner_department"]["id"] == FIN
    assert {d["id"] for d in body["allowed_departments"]} == {FIN, HR}

    docs = await _rows(
        engine, "SELECT id, title, owner_department_id, current_revision_id FROM documents"
    )
    assert len(docs) == 1 and str(docs[0].id) == body["document_id"]
    assert docs[0].current_revision_id is None  # never current before the Worker publishes
    revs = await _rows(
        engine,
        "SELECT id, status, storage_key, job_id, size_bytes, content_type FROM document_revisions",
    )
    assert len(revs) == 1 and revs[0].status == "queued" and revs[0].job_id is not None
    assert str(revs[0].id) == body["revision_id"]
    assert revs[0].storage_key == f"documents/{body['document_id']}/{body['revision_id']}.pdf"
    assert revs[0].content_type == "application/pdf" and revs[0].size_bytes == len(pdf)
    assert stored_keys(store) == [revs[0].storage_key]
    jobs = await _rows(engine, "SELECT id, job_type, status FROM jobs")
    assert [(j.job_type, j.status) for j in jobs] == [("ingest_revision", "queued")]
    assert jobs[0].id == revs[0].job_id
    outbox = await _rows(engine, "SELECT status FROM outbox")
    assert [o.status for o in outbox] == ["published"]  # published right after the commit
    assert [job for job, _ in publisher.published] == [jobs[0].id]
    audit = await _rows(
        engine, "SELECT event, user_id FROM audit_events WHERE event LIKE 'admin.%'"
    )
    assert [a.event for a in audit] == ["admin.document.created"]
    assert audit[0].user_id == admin.user_id


async def test_adm03_a_failed_publish_leaves_the_job_for_a_manual_retry(
    engine: AsyncEngine, clock: FakeClock, store: FakeObjectStore, admin: Any
) -> None:
    broken = FakePublisher(fail=True)
    async with await _client(engine, clock, store, broken) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages())
    assert response.status_code == 202
    outbox = await _rows(engine, "SELECT status, last_error FROM outbox")
    assert [o.status for o in outbox] == ["pending"] and outbox[0].last_error
    assert (await counts(engine))["documents"] == 1


# --- ADM-05 and OPEN-16: access is explicit and never inferred ----------------------------------


async def test_adm05_owner_a_allowed_b_writes_exactly_b(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(
            client, admin, pdf=pdf_two_pages(), data=upload_data(owner=FIN, allowed=(HR,))
        )
    assert response.status_code == 202
    access = await _rows(engine, "SELECT department_id FROM document_department_access")
    assert {str(a.department_id) for a in access} == {HR}  # the owner gets nothing implicitly


async def test_adm05_owner_a_allowed_a_writes_a_explicitly(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(
            client, admin, pdf=pdf_two_pages(), data=upload_data(owner=FIN, allowed=(FIN, FIN))
        )
    assert response.status_code == 202
    access = await _rows(engine, "SELECT department_id FROM document_department_access")
    assert [str(a.department_id) for a in access] == [FIN]


@pytest.mark.parametrize(
    ("allowed", "code"),
    [(None, "ALLOWED_DEPARTMENTS_MISSING"), ([""], "ALLOWED_DEPARTMENTS_EMPTY")],
)
async def test_adm05_missing_or_empty_allowed_list_is_422_and_creates_nothing(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    allowed: list[str] | None,
    code: str,
) -> None:
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(
            client, admin, pdf=pdf_two_pages(), data=upload_data(allowed=allowed)
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code
    await assert_nothing_created(engine, store)


@pytest.mark.parametrize("where", ["owner", "allowed", "mixed"])
async def test_adm04_unknown_department_creates_nothing_in_the_database_or_the_store(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    where: str,
) -> None:
    ghost = str(uuid.uuid4())
    data = {
        "owner": upload_data(owner=ghost, allowed=(FIN,)),
        "allowed": upload_data(owner=FIN, allowed=(ghost,)),
        "mixed": upload_data(owner=FIN, allowed=(FIN, ghost)),
    }[where]
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages(), data=data)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_DEPARTMENT"
    await assert_nothing_created(engine, store)
    assert publisher.published == []


# --- SEC-11 / M3-AC11: hostile uploads, nothing stored ------------------------------------------

HOSTILE_UPLOADS: list[tuple[str, dict[str, Any], int, str]] = [
    ("not-a-pdf-renamed", {"pdf": not_a_pdf()}, 422, "NOT_A_PDF"),
    ("wrong-signature", {"pdf": b"GIF89a" + pdf_two_pages()}, 422, "NOT_A_PDF"),
    ("signature-not-at-start", {"pdf": b"\n" + pdf_two_pages()}, 422, "NOT_A_PDF"),
    ("truncated", {"pdf": pdf_two_pages()[:-600]}, 422, "NOT_A_PDF"),
    ("header-only", {"pdf": pdf_corrupt()}, 422, "NOT_A_PDF"),
    ("empty", {"pdf": b""}, 422, "FILE_EMPTY"),
    ("html", {"pdf": b"<html><script>alert(1)</script></html>"}, 422, "NOT_A_PDF"),
    ("wrong-extension", {"pdf": pdf_two_pages(), "filename": "policy.exe"}, 422, "NOT_A_PDF"),
    ("no-extension", {"pdf": pdf_two_pages(), "filename": "policy"}, 422, "NOT_A_PDF"),
    (
        "overlong-name",
        {"pdf": pdf_two_pages(), "filename": "a" * 300 + ".pdf"},
        422,
        "INVALID_FILENAME",
    ),
    ("only-extension", {"pdf": pdf_two_pages(), "filename": ".pdf"}, 422, "INVALID_FILENAME"),
    ("rlm-in-name", {"pdf": pdf_two_pages(), "filename": "a‏b.pdf"}, 422, "INVALID_FILENAME"),
    ("empty-title", {"pdf": pdf_two_pages(), "title": "   "}, 422, "TITLE_INVALID"),
    ("long-title", {"pdf": pdf_two_pages(), "title": "t" * 201}, 422, "TITLE_INVALID"),
    ("bidi-title", {"pdf": pdf_two_pages(), "title": "Report ‮gnp"}, 422, "TITLE_INVALID"),
    ("nul-title", {"pdf": pdf_two_pages(), "title": "Re\x00port"}, 422, "TITLE_INVALID"),
    ("newline-title", {"pdf": pdf_two_pages(), "title": "Re\nport"}, 422, "TITLE_INVALID"),
]


EXTRA_HOSTILE = ["a\nb.pdf", "a\rb.pdf", "x/y.pdf", "‮.pdf"]


@pytest.mark.parametrize("name", [*HOSTILE_NAMES, *EXTRA_HOSTILE])
def test_sec11_hostile_file_names_are_rejected_by_the_validator(name: str) -> None:
    """Raw names, before any transport mangling (httpx and python-multipart rewrite some)."""
    from knowserve_api.admin.validation import validate_filename
    from knowserve_core.web import AppError

    with pytest.raises(AppError) as exc:
        validate_filename(name)
    assert exc.value.code == "INVALID_FILENAME"


@pytest.mark.parametrize("name", HOSTILE_NAMES)
async def test_sec11_hostile_names_over_http_are_rejected_or_stored_safely(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    name: str,
) -> None:
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages(), filename=name)
    if response.status_code == 422:
        await assert_nothing_created(engine, store)
        return
    assert response.status_code == 202
    stored = response.json()["filename"]
    assert not any(c in stored for c in ("/", "\\", "\x00", "‮")) and ".." not in stored
    assert all(KEY_RE.match(k) for k in stored_keys(store))


@pytest.mark.parametrize(
    ("case", "overrides", "status", "code"), HOSTILE_UPLOADS, ids=[c[0] for c in HOSTILE_UPLOADS]
)
async def test_sec11_hostile_upload_is_rejected_and_leaves_nothing(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    case: str,
    overrides: dict[str, Any],
    status: int,
    code: str,
) -> None:
    kwargs: dict[str, Any] = {"pdf": overrides["pdf"]}
    if "filename" in overrides:
        kwargs["filename"] = overrides["filename"]
    if "title" in overrides:
        kwargs["data"] = upload_data(title=overrides["title"])
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(client, admin, **kwargs)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    await assert_nothing_created(engine, store)
    assert publisher.published == []


async def test_sec11_oversize_pdf_is_413_and_leaves_nothing(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    pdf = pdf_two_pages()
    async with await _client(
        engine, clock, store, publisher, upload_max_pdf_bytes=len(pdf) - 1
    ) as c:
        too_big = await post_document(c, admin, pdf=pdf)
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "FILE_TOO_LARGE"
    await assert_nothing_created(engine, store)
    async with await _client(engine, clock, store, publisher, upload_max_pdf_bytes=len(pdf)) as c:
        exact = await post_document(c, admin, pdf=pdf)
    assert exact.status_code == 202  # the limit is inclusive


@pytest.mark.parametrize("pdf_fn", [pdf_encrypted, pdf_image_only])
async def test_adm18_encrypted_and_image_only_pdfs_pass_to_the_worker(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    pdf_fn: Any,
) -> None:
    """The Worker fails these with PDF_ENCRYPTED and NO_EXTRACTABLE_TEXT, so the Admin can see
    the reason and replace the file (OPEN-17, M3-AC06); the API does not pre-judge them."""
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_fn())
    assert response.status_code == 202


# --- Storage keys and mass assignment -----------------------------------------------------------


async def test_sec11_storage_keys_are_server_generated_and_free_of_client_input(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(
            client,
            admin,
            pdf=pdf_two_pages(),
            filename="client-chosen name (final).pdf",
            data=upload_data(title="../../etc/passwd client title"),
        )
    assert response.status_code == 202
    keys = stored_keys(store)
    assert len(keys) == 1 and KEY_RE.match(keys[0])
    for needle in ("client", "chosen", "final", "passwd", ".."):
        assert needle not in keys[0]
    stored = await _rows(engine, "SELECT storage_key FROM document_revisions")
    assert [r.storage_key for r in stored] == keys


@pytest.mark.parametrize(
    "field",
    [
        "status",
        "document_id",
        "revision_id",
        "job_id",
        "current_revision_id",
        "storage_key",
        "deleted_at",
        "phase",
        "page_count",
        "filename",
    ],
)
async def test_adm03_mass_assignment_is_rejected_and_creates_nothing(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    field: str,
) -> None:
    value = str(uuid.uuid4()) if field.endswith("_id") else "ready"
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(
            client, admin, pdf=pdf_two_pages(), data=upload_data(extra={field: value})
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    await assert_nothing_created(engine, store)


# --- M3-AC26: the upload switch -----------------------------------------------------------------


async def test_m3_ac26_disabled_uploads_create_nothing_for_a_valid_request(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher, uploads_enabled=False) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPLOADS_DISABLED"
    await assert_nothing_created(engine, store)


# --- M3-AC03 / ADM-03: atomicity with fault injection -------------------------------------------


async def test_m3_ac03_a_fault_after_the_outbox_insert_leaves_no_rows_and_no_object(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected fault after the job and outbox rows were written")

    # The audit row is written after enqueue_job (job + outbox) inside the same transaction.
    monkeypatch.setattr("knowserve_api.admin.creation.audit.record", boom)
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages())
    assert response.status_code == 500
    await assert_nothing_created(engine, store)
    assert publisher.published == []


async def test_m3_ac03_a_fault_while_writing_the_idempotency_row_rolls_everything_back(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowserve_api.admin.creation import UploadService

    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected fault at the last write")

    monkeypatch.setattr(UploadService, "add_idempotency_row", staticmethod(boom))
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages())
    assert response.status_code == 500
    await assert_nothing_created(engine, store)


async def test_m3_ac03_an_object_store_failure_creates_no_rows(
    engine: AsyncEngine, clock: FakeClock, publisher: FakePublisher, admin: Any
) -> None:
    class DownStore(FakeObjectStore):
        async def put(self, key: str, data: bytes, content_type: str) -> None:
            raise ObjectStoreError("down")

    down = DownStore()
    async with await _client(engine, clock, down, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    await assert_nothing_created(engine, down)


async def test_m3_ac03_a_failed_cleanup_is_logged_and_does_not_hide_the_original_error(
    engine: AsyncEngine,
    clock: FakeClock,
    publisher: FakePublisher,
    admin: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class StuckDelete(FakeObjectStore):
        async def delete(self, key: str) -> None:
            raise ObjectStoreError("delete refused")

    stuck = StuckDelete()

    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("injected")

    monkeypatch.setattr("knowserve_api.admin.creation.audit.record", boom)
    async with await _client(engine, clock, stuck, publisher) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages())
    assert response.status_code == 500
    assert (await counts(engine))["documents"] == 0
    leftover = stored_keys(stuck)
    assert len(leftover) == 1
    assert leftover[0] in capsys.readouterr().out


# --- ADM-13: idempotency -------------------------------------------------------------------------


async def test_adm13_the_same_key_and_request_replays_the_first_result(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    pdf = pdf_two_pages()
    async with await _client(engine, clock, store, publisher) as client:
        first = await post_document(client, admin, pdf=pdf, key="replay-key-0001")
        second = await post_document(client, admin, pdf=pdf, key="replay-key-0001")
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    counted = await counts(engine)
    assert (counted["documents"], counted["document_revisions"], counted["jobs"]) == (1, 1, 1)
    assert counted["outbox"] == 1 and counted["admin_idempotency_keys"] == 1
    assert len(stored_keys(store)) == 1 and len(publisher.published) == 1


@pytest.mark.parametrize(
    "change",
    ["file", "title", "owner", "allowed", "filename"],
)
async def test_adm13_the_same_key_with_different_content_is_409(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    change: str,
) -> None:
    base = {"pdf": pdf_two_pages(), "filename": "policy.pdf", "data": upload_data()}
    other: dict[str, Any] = {**base}
    if change == "file":
        other["pdf"] = make_pdf(["A different document body."])
    elif change == "title":
        other["data"] = upload_data(title="Another title")
    elif change == "owner":
        other["data"] = upload_data(owner=ENG)
    elif change == "allowed":
        other["data"] = upload_data(allowed=(FIN, LEGAL))
    else:
        other["filename"] = "renamed.pdf"
    async with await _client(engine, clock, store, publisher) as client:
        first = await post_document(client, admin, key="reuse-key-00001", **base)
        second = await post_document(client, admin, key="reuse-key-00001", **other)
    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (await counts(engine))["documents"] == 1
    assert len(stored_keys(store)) == 1


async def test_adm13_keys_are_scoped_to_the_admin_and_the_operation(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    make_user: Any,
    make_session: Any,
) -> None:
    other_admin = await make_session(await make_user("admin"))
    pdf = pdf_two_pages()
    async with await _client(engine, clock, store, publisher) as client:
        mine = await post_document(client, admin, pdf=pdf, key="shared-key-0001")
        theirs = await post_document(client, other_admin, pdf=pdf, key="shared-key-0001")
        # A row of another operation under the same key is a different request, not a replay.
        await _insert_key(engine, admin.user_id, "op-key-000001", "replace_document")
        crossed = await post_document(client, admin, pdf=pdf, key="op-key-000001")
    assert mine.status_code == theirs.status_code == 202
    assert mine.json()["document_id"] != theirs.json()["document_id"]
    assert crossed.status_code == 409
    assert crossed.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def _insert_key(engine: AsyncEngine, admin_id: uuid.UUID, key: str, operation: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO admin_idempotency_keys "
                "(admin_user_id, idempotency_key, operation, request_hash, result_status, result) "
                "VALUES (:u, :k, :o, :h, 202, '{}'::jsonb)"
            ),
            {"u": admin_id, "k": key, "o": operation, "h": "0" * 64},
        )


async def test_adm13_a_replay_still_needs_the_session_csrf_and_the_admin_role(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    make_user: Any,
    make_session: Any,
) -> None:
    registered = await make_session(await make_user("registered"))
    async with await _client(engine, clock, store, publisher) as client:
        first = await post_document(client, admin, pdf=pdf_two_pages(), key="guarded-key-001")
        denied = await post_document(client, registered, pdf=pdf_two_pages(), key="guarded-key-001")
        no_csrf = await post_document(
            client, admin, pdf=pdf_two_pages(), key="guarded-key-001", csrf=False
        )
    assert first.status_code == 202
    assert denied.status_code == 403
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "CSRF_INVALID"


async def test_adm13_concurrent_duplicates_create_one_document_and_leave_one_object(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    pdf = pdf_two_pages()
    async with await _client(engine, clock, store, publisher) as client:
        responses = await asyncio.gather(
            *[post_document(client, admin, pdf=pdf, key="race-key-00001") for _ in range(6)]
        )
    assert [r.status_code for r in responses] == [202] * 6, [r.text for r in responses]
    assert len({r.json()["document_id"] for r in responses}) == 1
    assert len({r.json()["revision_id"] for r in responses}) == 1
    counted = await counts(engine)
    assert (counted["documents"], counted["document_revisions"], counted["jobs"]) == (1, 1, 1)
    assert counted["outbox"] == 1 and counted["document_department_access"] == 1
    assert counted["admin_idempotency_keys"] == 1
    # The losers rolled back and deleted their own objects: only the winner's remains.
    assert stored_keys(store) == [
        f"documents/{responses[0].json()['document_id']}/{responses[0].json()['revision_id']}.pdf"
    ]
    assert len(publisher.published) == 1


# --- OPEN-31 D1: limits ---------------------------------------------------------------------------


async def test_d1_the_in_flight_limit_answers_429_and_creates_nothing_more(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher, upload_max_in_flight=2) as client:
        for _ in range(2):
            assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 202
        full = await post_document(client, admin, pdf=pdf_two_pages(), key="blocked-key-001")
        assert full.status_code == 429
        assert full.json()["error"]["code"] == "UPLOAD_BACKLOG_FULL"
        assert (await counts(engine))["documents"] == 2 and len(stored_keys(store)) == 2
        # A replay of a stored request still answers while the backlog is full.
        replay = await post_document(client, admin, pdf=pdf_two_pages(), key="blocked-key-001")
        assert replay.status_code == 429  # it never succeeded, so there is nothing to replay
        # Finishing a document frees a slot.
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE document_revisions SET status = 'failed' WHERE id IN "
                    "(SELECT id FROM document_revisions LIMIT 1)"
                )
            )
        assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 202


async def test_d1_a_soft_deleted_document_does_not_count_as_in_flight(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(engine, clock, store, publisher, upload_max_in_flight=1) as client:
        assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 202
        assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 429
        async with engine.begin() as conn:
            await conn.execute(text("UPDATE documents SET deleted_at = now()"))
        assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 202


async def test_d1_the_daily_limit_resets_at_the_utc_day_boundary(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(
        engine, clock, store, publisher, upload_max_per_day=2, upload_max_in_flight=50
    ) as client:
        for _ in range(2):
            assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 202
        capped = await post_document(client, admin, pdf=pdf_two_pages())
        assert capped.status_code == 429
        assert capped.json()["error"]["code"] == "DAILY_UPLOAD_LIMIT"
        clock.advance(hours=11, minutes=59)  # 23:59 UTC, still the same day
        assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 429
        clock.advance(minutes=2)  # past midnight UTC
        assert (await post_document(client, admin, pdf=pdf_two_pages())).status_code == 202


async def test_d1_concurrent_uploads_cannot_overshoot_the_daily_limit(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with await _client(
        engine, clock, store, publisher, upload_max_per_day=1, upload_max_in_flight=50
    ) as client:
        responses = await asyncio.gather(
            *[post_document(client, admin, pdf=pdf_two_pages()) for _ in range(5)]
        )
    codes = sorted(r.status_code for r in responses)
    assert codes == [202, 429, 429, 429, 429], [r.text for r in responses]
    assert (await counts(engine))["documents"] == 1
    assert len(stored_keys(store)) == 1  # the 429 losers removed their objects


# --- MON-05, SEC-18, ADM-17: audit and log hygiene -----------------------------------------------


async def test_mon05_audit_rows_and_logs_hold_no_document_text_or_file_names(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "CONFIDENTIAL-MARKER-4711"
    pdf = make_pdf([f"Salary table {marker}"])
    async with await _client(engine, clock, store, publisher) as client:
        response = await post_document(
            client,
            admin,
            pdf=pdf,
            filename="salaries-secret-name.pdf",
            data=upload_data(title="Salary review 2026"),
        )
    assert response.status_code == 202
    audit = await _rows(
        engine, "SELECT details::text AS d FROM audit_events WHERE event LIKE 'admin.%'"
    )
    assert len(audit) == 1
    logs = capsys.readouterr().out
    assert "admin.document.created" in logs  # the capture is live, so the checks below mean it
    text_blob = audit[0].d + "\n" + logs
    for forbidden in (marker, "salaries-secret-name", "Salary review", "Salary table"):
        assert forbidden not in text_blob
    details = await _rows(
        engine, "SELECT details FROM audit_events WHERE event = 'admin.document.created'"
    )
    assert set(details[0].details) == {
        "document_id",
        "revision_id",
        "owner_department_id",
        "allowed_department_ids",
        "size_bytes",
        "source",
    }
