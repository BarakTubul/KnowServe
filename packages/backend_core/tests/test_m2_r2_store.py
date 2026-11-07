"""M2-03: R2ObjectStore over a mock transport, SigV4 against AWS's published example, factory guard.

No R2 end-to-end evidence is possible locally (M2-00c); these tests pin the request shape and the
error hygiene (no URL, host or credential in an exception or a log).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import pytest

from knowserve_core.logging import quiet_http_clients
from knowserve_core.object_store import (
    ByteRange,
    ObjectNotFound,
    ObjectStoreError,
    R2Config,
    R2ObjectStore,
    build_object_store,
    sign_v4,
)

pytestmark = [pytest.mark.m2, pytest.mark.documents]

ENDPOINT = "https://acct123.r2.cloudflarestorage.com"
KEY_ID = "AKIAEXAMPLEKEYID"
SECRET = "super-secret-access-key-value"


def _store(handler: httpx.MockTransport | None = None, **kw: object) -> R2ObjectStore:
    client = httpx.AsyncClient(transport=handler) if handler else None
    return R2ObjectStore(
        endpoint=ENDPOINT,
        bucket="docs-bucket",
        access_key_id=KEY_ID,
        secret_access_key=SECRET,
        client=client,
        **kw,  # type: ignore[arg-type]
    )


def test_m2_sigv4_matches_the_aws_published_get_object_range_example() -> None:
    signed = sign_v4(
        method="GET",
        url="https://examplebucket.s3.amazonaws.com/test.txt",
        headers={"Range": "bytes=0-9"},
        payload_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        now=datetime(2013, 5, 24, 0, 0, 0, tzinfo=UTC),
    )
    assert signed["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


async def test_m2_r2_size_uses_a_signed_path_style_head() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-length": "1234"})

    store = _store(httpx.MockTransport(handler))
    assert await store.size("documents/a b/c.pdf") == 1234
    request = seen[0]
    assert request.method == "HEAD"
    assert request.url.raw_path == b"/docs-bucket/documents/a%20b/c.pdf"
    auth = request.headers["authorization"]
    assert auth.startswith(f"AWS4-HMAC-SHA256 Credential={KEY_ID}/")
    assert "/auto/s3/aws4_request" in auth
    assert SECRET not in auth


async def test_m2_r2_ranged_stream_sends_an_inclusive_signed_range() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(206, content=b"0123456789")

    store = _store(httpx.MockTransport(handler))
    body = b"".join([c async for c in store.stream("k.pdf", ByteRange(5, 14))])
    assert body == b"0123456789"
    assert seen[0].headers["range"] == "bytes=5-14"
    assert "range" in seen[0].headers["authorization"].split("SignedHeaders=")[1].split(",")[0]


async def test_m2_r2_put_sends_payload_hash_and_content_type() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    store = _store(httpx.MockTransport(handler))
    await store.put("k.pdf", b"abc", "application/pdf")
    assert seen[0].method == "PUT"
    assert seen[0].headers["content-type"] == "application/pdf"
    assert seen[0].headers["x-amz-content-sha256"] != "UNSIGNED-PAYLOAD"
    assert seen[0].content == b"abc"


async def test_m2_r2_missing_object_maps_to_object_not_found() -> None:
    store = _store(httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(ObjectNotFound):
        await store.size("nope.pdf")
    with pytest.raises(ObjectNotFound):
        _ = [c async for c in store.stream("nope.pdf")]


async def test_sec06_r2_errors_never_carry_url_host_or_credentials(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("httpx", "httpcore"):  # restore the levels afterwards
        monkeypatch.setattr(logging.getLogger(name), "level", logging.getLogger(name).level)
    quiet_http_clients()  # what configure_logging does at API startup

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection to acct123.r2.cloudflarestorage.com failed")

    for transport in (
        httpx.MockTransport(boom),
        httpx.MockTransport(lambda r: httpx.Response(403)),
    ):
        store = _store(transport)
        with pytest.raises(ObjectStoreError) as excinfo:
            await store.size("documents/x/y.pdf")
        text = str(excinfo.value)
        assert "r2.cloudflarestorage" not in text
        assert "docs-bucket" not in text
    for secret in (SECRET, KEY_ID, "r2.cloudflarestorage", "docs-bucket", "documents/x/y.pdf"):
        assert secret not in caplog.text


async def test_m2_r2_unsigned_redirects_are_not_followed() -> None:
    store = _store()
    assert store._client.follow_redirects is False  # pyright: ignore[reportPrivateUsage]
    await store.aclose()


def _r2(**over: str | None) -> R2Config:
    values: dict[str, str | None] = {
        "endpoint": ENDPOINT,
        "bucket": "b",
        "access_key_id": "k",
        "secret_access_key": "s",
    }
    values.update(over)
    return R2Config(**values)


def test_m2_factory_builds_r2_with_full_config_in_production() -> None:
    assert isinstance(build_object_store("r2", env="production", r2=_r2()), R2ObjectStore)


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("endpoint", "KS_R2_ENDPOINT"),
        ("bucket", "KS_R2_BUCKET"),
        ("access_key_id", "KS_R2_ACCESS_KEY_ID"),
        ("secret_access_key", "KS_R2_SECRET_ACCESS_KEY"),
    ],
)
def test_m2_factory_names_the_missing_r2_setting(field: str, name: str) -> None:
    with pytest.raises(ValueError, match=name):
        build_object_store("r2", env="production", r2=_r2(**{field: None}))


def test_m2_factory_refuses_r2_without_any_config_and_plain_http() -> None:
    with pytest.raises(ValueError, match="KS_R2_ENDPOINT"):
        build_object_store("r2", env="local")
    with pytest.raises(ValueError, match="https"):
        build_object_store("r2", env="local", r2=_r2(endpoint="http://x"))


def test_m2_factory_production_refusal_names_the_fix() -> None:
    with pytest.raises(ValueError, match="KS_OBJECT_STORE=r2"):
        build_object_store("fake", env="production")
