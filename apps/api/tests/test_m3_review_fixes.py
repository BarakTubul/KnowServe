"""Regression tests for the independent review of M3-03 and M3-04 (hard gates, no skips)."""

from __future__ import annotations

import asyncio
import struct
import uuid
from typing import Any

import pytest
from m3_upload_support import (
    assert_nothing_created,
    counts,
    make_app,
    make_client,
    post_document,
    stored_keys,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from test_m3_import import _client, _good, _post  # noqa: F401  (fixtures: store, publisher, admin)

from knowserve_api.body_limit import HEADROOM_BYTES
from knowserve_core.clock import FakeClock
from knowserve_core.object_store import FakeObjectStore
from knowserve_core.qstash import FakePublisher
from knowserve_core.testing_fixtures import (
    make_pdf,
    make_zip,
    manifest_entry,
    manifest_json,
    pdf_two_pages,
    zip_bomb,
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


# --- 1. The body is capped before auth and before parsing -------------------------------------


FORGED_COOKIE = b"other=1; ks_session=not-a-real-session"


async def _asgi(app: Any, headers: list[tuple[bytes, bytes]], chunks: Any) -> tuple[int, dict]:
    sent: dict[str, Any] = {"status": None, "body": b""}
    chunk_iter = iter(chunks)
    reads = {"n": 0}

    async def receive() -> dict[str, Any]:
        reads["n"] += 1
        try:
            return {"type": "http.request", "body": next(chunk_iter), "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
        else:
            sent["body"] += message.get("body", b"")

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/admin/documents",
        "raw_path": b"/v1/admin/documents",
        "query_string": b"",
        "headers": headers,
        "scheme": "https",
        "server": ("api.test", 443),
        "client": ("1.2.3.4", 1),
        "http_version": "1.1",
    }
    await app(scope, receive, send)
    return sent["status"], {"body": sent["body"], "reads": reads["n"]}


async def test_sec11_oversized_unauthenticated_upload_is_413_before_any_body_is_read(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(engine, clock, upload_max_pdf_bytes=1000, upload_max_zip_bytes=1000)
    boundary = b"multipart/form-data; boundary=x"
    headers = [
        (b"content-type", boundary),
        (b"content-length", str(10_000_000).encode()),
        (b"cookie", FORGED_COOKIE),
    ]
    status, info = await _asgi(app, headers, [])
    assert status == 413
    assert b"FILE_TOO_LARGE" in info["body"]
    assert info["reads"] == 0  # rejected from the header alone


async def test_sec11_a_body_without_content_length_is_cut_off_at_the_limit(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(engine, clock, upload_max_pdf_bytes=1000, upload_max_zip_bytes=1000)
    headers = [(b"content-type", b"multipart/form-data; boundary=x"), (b"cookie", FORGED_COOKIE)]
    chunk = b"a" * 16_384
    opening = b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n'
    status, info = await _asgi(app, headers, [opening] + [chunk] * 5_000)  # 80 MB offered
    assert status == 413
    assert info["reads"] < (1000 + HEADROOM_BYTES) // len(chunk) + 4  # nowhere near all of it


async def test_sec11_normal_unauthenticated_upload_is_still_401_and_admin_still_works(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    class Anonymous:
        headers: dict[str, str] = {"X-CSRF-Token": "x", "Origin": "http://localhost:5173"}
        cookies: dict[str, str] = {}

    async with make_client(make_app(engine, clock, store=store, publisher=publisher)) as client:
        anonymous = await post_document(client, Anonymous(), pdf=pdf_two_pages())
        ok = await post_document(client, admin, pdf=pdf_two_pages())
    assert anonymous.status_code == 401
    assert ok.status_code == 202


async def test_sec11_anonymous_oversized_upload_is_401_without_reading_the_body(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(engine, clock, upload_max_pdf_bytes=1000, upload_max_zip_bytes=1000)
    headers = [
        (b"content-type", b"multipart/form-data; boundary=x"),
        (b"content-length", b"10000000"),
        (b"cookie", b"other=1"),  # a cookie, but not the session cookie
    ]
    status, info = await _asgi(app, headers, [])
    assert status == 401
    assert b"UNAUTHENTICATED" in info["body"]
    assert info["reads"] == 0


async def test_sec11_anonymous_malformed_multipart_is_401_not_400_and_reads_nothing(
    engine: AsyncEngine, clock: FakeClock
) -> None:
    app = make_app(engine, clock)
    headers = [(b"content-type", b"multipart/form-data; boundary=x")]
    status, info = await _asgi(app, headers, [b"garbage" * 1000] * 50)
    assert status == 401
    assert info["reads"] == 0


async def test_sec11_a_bad_session_cookie_value_still_gets_the_normal_401(
    engine: AsyncEngine, clock: FakeClock, store: FakeObjectStore, publisher: FakePublisher
) -> None:
    class Forged:
        headers: dict[str, str] = {"X-CSRF-Token": "x", "Origin": "http://localhost:5173"}
        cookies: dict[str, str] = {"ks_session": "not-a-real-session"}

    async with make_client(make_app(engine, clock, store=store, publisher=publisher)) as client:
        response = await post_document(client, Forged(), pdf=pdf_two_pages())
    assert response.status_code == 401  # the auth dependency, not the cheap guard
    await assert_nothing_created(engine, store)


# --- 2, 3, 4. Archive guards ---------------------------------------------------------------------


def _patch(raw: bytes, signature: bytes, offset: int, value: int, size: int = 4) -> bytes:
    data = bytearray(raw)
    at = 0
    while (at := data.find(signature, at)) != -1:
        data[at + offset : at + offset + size] = value.to_bytes(size, "little")
        at += 4
    return bytes(data)


async def test_sec11_a_zip64_locator_cannot_bypass_the_directory_guard(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    raw = _good(1)
    eocd = raw.rfind(b"PK\x05\x06")
    locator = b"PK\x06\x07" + struct.pack("<IQI", 0, eocd, 1)
    data = raw[:eocd] + locator + raw[eocd:]
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", data)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ZIP_INVALID"
    await assert_nothing_created(engine, store)


async def test_sec11_a_lying_compress_size_does_not_hide_a_zip_bomb(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    raw = zip_bomb()
    lie = 5 * 1024 * 1024
    raw = _patch(raw, b"PK\x01\x02", 20, lie)  # central directory
    raw = _patch(raw, b"PK\x03\x04", 18, lie)  # local header
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", raw)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ZIP_RATIO_EXCEEDED"


async def test_sec11_corrupt_deflate_data_is_a_422_not_a_500(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    pdf = make_pdf(["compressible text " * 40])
    raw = bytearray(make_zip({"a.pdf": pdf}, manifest_json([manifest_entry("a.pdf")])))
    start = 30 + len("a.pdf")  # the deflate stream follows the first local header
    raw[start + 2 : start + 12] = bytes(10 * [255])
    async with _client(engine, clock, store, publisher) as client:
        preview = await _post(client, admin, "preview", bytes(raw))
        confirm = await _post(client, admin, "confirm", bytes(raw), key="corrupt-key-0001")
    # A damaged member is that entry's problem, reported per entry: never a 500.
    assert preview.status_code == 200, preview.text
    assert preview.json()["entries"][0]["error_code"] == "ZIP_INVALID"
    assert confirm.status_code < 500, confirm.text
    assert "ZIP_INVALID" in confirm.text
    assert (await counts(engine))["documents"] == 0 and not stored_keys(store)


# --- 5. A duplicate waiting on the limit lock replays ---------------------------------------------


async def test_adm13_concurrent_duplicates_replay_even_when_the_backlog_is_one(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    async with _client(engine, clock, store, publisher, upload_max_in_flight=1) as client:
        responses = await asyncio.gather(
            *[
                post_document(client, admin, pdf=pdf_two_pages(), key="lock-replay-001")
                for _ in range(6)
            ]
        )
    assert [r.status_code for r in responses] == [202] * 6, [r.text for r in responses]
    assert (await counts(engine))["documents"] == 1 and len(stored_keys(store)) == 1


# --- 6. Only one confirm finishes the batch -----------------------------------------------------


async def test_adm14_a_batch_already_finished_elsewhere_is_not_audited_twice(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowserve_api.admin import imports as imports_module

    real = imports_module._create_entry

    async def finish_elsewhere(*args: Any, **kwargs: Any) -> Any:
        outcome = await real(*args, **kwargs)
        async with engine.begin() as conn:  # a concurrent confirm completed the batch
            await conn.execute(
                text("UPDATE admin_idempotency_keys SET result_status = 200, result = '{}'::jsonb")
            )
        return outcome

    monkeypatch.setattr(imports_module, "_create_entry", finish_elsewhere)
    async with _client(engine, clock, store, publisher) as client:
        await _post(client, admin, "confirm", _good(1), key="finish-key-00001")
    async with engine.connect() as conn:
        audited = (
            await conn.execute(
                text("SELECT count(*) FROM audit_events WHERE event = 'admin.import.confirmed'")
            )
        ).scalar_one()
        stored = (
            await conn.execute(text("SELECT result::text FROM admin_idempotency_keys"))
        ).scalar_one()
    assert audited == 0
    assert stored == "{}"  # the finished result was not overwritten


# --- 7. Echoed names are bounded and clean ---


async def test_sec11_echoed_file_names_are_truncated_and_stripped_of_bidi_controls(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    hostile = "evil‮" + "x" * 400 + ".pdf"
    data = make_zip(
        {"ok.pdf": pdf_two_pages()},
        manifest_json([manifest_entry("ok.pdf"), manifest_entry(hostile)]),
    )
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", data)
    shown = response.json()["entries"][1]
    assert shown["valid"] is False
    assert "‮" not in shown["file"] and len(shown["file"]) <= 200


# --- 9. Department lists are capped --------------------------------------------------------------


async def test_adm03_more_than_50_allowed_departments_is_a_validation_error(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    from m3_upload_support import upload_data

    data = upload_data()
    data["allowed_department_ids"] = [str(uuid.uuid4()) for _ in range(51)]
    async with make_client(make_app(engine, clock, store=store, publisher=publisher)) as client:
        response = await post_document(client, admin, pdf=pdf_two_pages(), data=data)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    await assert_nothing_created(engine, store)


async def test_adm13_a_manifest_entry_with_more_than_50_departments_is_invalid(
    engine: AsyncEngine,
    clock: FakeClock,
    store: FakeObjectStore,
    publisher: FakePublisher,
    admin: Any,
) -> None:
    entry = manifest_entry("big.pdf")
    entry["allowed_departments"] = ["finance"] * 51
    data = make_zip(
        {"ok.pdf": pdf_two_pages(), "big.pdf": pdf_two_pages()},
        manifest_json([manifest_entry("ok.pdf"), entry]),
    )
    async with _client(engine, clock, store, publisher) as client:
        response = await _post(client, admin, "preview", data)
    entries = response.json()["entries"]
    assert [e["valid"] for e in entries] == [True, False]
    assert entries[1]["error_code"] == "MANIFEST_INVALID"
