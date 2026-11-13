"""Object storage interface for document bytes (ARCH-14, Q6).

Three implementations: ``FakeObjectStore`` (in memory, tests), ``FilesystemObjectStore`` (local
development) and ``R2ObjectStore`` (production, over the S3 API). No method returns a URL: bytes
always pass through the API (DOC-04). ``build_object_store`` refuses the fake and filesystem stores
in production, like the Firebase emulator guard.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

logger = logging.getLogger("knowserve.object_store")

CHUNK_SIZE = 64 * 1024


class ObjectNotFound(Exception):
    """The key does not exist in the store."""


class ObjectStoreError(Exception):
    """The backing store failed (network, auth, 5xx). Never carries a URL or credentials."""


@dataclass(frozen=True)
class ByteRange:
    """Inclusive byte range with ``0 <= start <= end``.

    Construction checks only the invariants. Callers must also check ``end`` against the object
    size from ``ObjectStore.size`` before building one.
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid byte range {self.start}-{self.end}")

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None:
        """Remove the object. Deleting a missing key is not an error (the call is idempotent).

        Used by the API to clean up an object whose database transaction failed (M3-AC03). The
        Worker's credential is read-only and never calls it (OPEN-31 D6).
        """
        ...

    async def size(self, key: str) -> int:
        """Size in bytes (head). Raises ``ObjectNotFound``."""
        ...

    def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        """Yield the object, or only ``byte_range``, in chunks. Raises ``ObjectNotFound``."""
        ...


class FakeObjectStore:
    """In-memory store for automated tests."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = data

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)

    async def size(self, key: str) -> int:
        try:
            return len(self._objects[key])
        except KeyError:
            raise ObjectNotFound(key) from None

    async def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        try:
            data = self._objects[key]
        except KeyError:
            raise ObjectNotFound(key) from None
        if byte_range is not None:
            data = data[byte_range.start : byte_range.end + 1]
        for i in range(0, len(data), CHUNK_SIZE):
            yield data[i : i + CHUNK_SIZE]


class FilesystemObjectStore:
    """Local development store rooted at a directory. Keys cannot escape the root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root != path and self._root not in path.parents:
            raise ObjectNotFound(key)
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def delete(self, key: str) -> None:
        try:
            path = self._path(key)
        except ObjectNotFound:
            return
        path.unlink(missing_ok=True)

    async def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.stat().st_size

    async def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        with path.open("rb") as handle:
            remaining: int | None = None
            if byte_range is not None:
                handle.seek(byte_range.start)
                remaining = byte_range.length
            while remaining is None or remaining > 0:
                chunk = handle.read(CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk


EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sign_v4(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload_sha256: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    now: datetime,
    service: str = "s3",
) -> dict[str, str]:
    """AWS Signature Version 4 headers for one request (S3 / R2).

    Returns the headers to add: ``x-amz-date``, ``x-amz-content-sha256`` and ``Authorization``.
    ``headers`` are signed too (``host`` is derived from the URL and must not be passed). The key
    must already be percent-encoded in ``url`` and the URL must have no query string.
    """
    parts = urlsplit(url)
    amz_date = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    to_sign = {k.lower(): " ".join(v.split()) for k, v in headers.items()}
    to_sign["host"] = parts.netloc
    to_sign["x-amz-date"] = amz_date
    to_sign["x-amz-content-sha256"] = payload_sha256
    names = sorted(to_sign)
    canonical_headers = "".join(f"{n}:{to_sign[n]}\n" for n in names)
    signed = ";".join(names)
    canonical = "\n".join(
        [method, parts.path or "/", parts.query, canonical_headers, signed, payload_sha256]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    key = _hmac(("AWS4" + secret_access_key).encode(), day)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "x-amz-date": amz_date,
        "x-amz-content-sha256": payload_sha256,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
            f"SignedHeaders={signed}, Signature={signature}"
        ),
    }


class R2ObjectStore:
    """Cloudflare R2 over the S3 API (path-style, SigV4, region ``auto``).

    Built on ``httpx`` (already a dependency) instead of boto3 to keep the image and the lockfile
    unchanged; only HEAD, ranged GET and PUT are needed. Errors never include the URL, the bucket
    host or credentials, so nothing storage-specific can reach a client or a log (DOC-04, MON-05).
    Verified locally against a mock transport only; no R2 end-to-end evidence until M2-00c.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        client: httpx.AsyncClient | None = None,
        region: str = "auto",
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._bucket = bucket
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, read=30.0), follow_redirects=False
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _request(
        self,
        method: str,
        key: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> httpx.Request:
        url = f"{self._endpoint}/{quote(self._bucket, safe='')}/{quote(key, safe='/-_.~')}"
        extra = dict(headers or {})
        payload = hashlib.sha256(body).hexdigest() if body is not None else EMPTY_SHA256
        signed = sign_v4(
            method=method,
            url=url,
            headers=extra,
            payload_sha256=payload,
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            region=self._region,
            now=datetime.now(UTC),
        )
        return self._client.build_request(method, url, headers={**extra, **signed}, content=body)

    async def _send(self, request: httpx.Request, *, stream: bool = False) -> httpx.Response:
        try:
            return await self._client.send(request, stream=stream)
        except httpx.HTTPError as exc:
            logger.error("object store request failed", extra={"error_type": type(exc).__name__})
            raise ObjectStoreError("object store unavailable") from None

    @staticmethod
    def _fail(status: int) -> ObjectStoreError:
        logger.error("object store returned an error", extra={"status": status})
        return ObjectStoreError(f"object store error {status}")

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        response = await self._send(
            self._request("PUT", key, headers={"content-type": content_type}, body=data)
        )
        if response.status_code not in (200, 201, 204):
            raise self._fail(response.status_code)

    async def delete(self, key: str) -> None:
        response = await self._send(self._request("DELETE", key))
        # S3 answers 204 for a missing key; a 404 is treated the same way.
        if response.status_code not in (200, 204, 404):
            raise self._fail(response.status_code)

    async def size(self, key: str) -> int:
        response = await self._send(self._request("HEAD", key))
        if response.status_code == 404:
            raise ObjectNotFound(key)
        if response.status_code != 200:
            raise self._fail(response.status_code)
        try:
            return int(response.headers["content-length"])
        except (KeyError, ValueError):
            raise ObjectStoreError("object store returned no size") from None

    async def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        headers = {}
        if byte_range is not None:
            headers["range"] = f"bytes={byte_range.start}-{byte_range.end}"
        response = await self._send(self._request("GET", key, headers=headers), stream=True)
        try:
            if response.status_code == 404:
                raise ObjectNotFound(key)
            if response.status_code not in (200, 206):
                raise self._fail(response.status_code)
            try:
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    yield chunk
            except httpx.HTTPError as exc:
                logger.error("object store stream failed", extra={"error_type": type(exc).__name__})
                raise ObjectStoreError("object store stream failed") from None
        finally:
            await response.aclose()


@dataclass(frozen=True)
class R2Config:
    endpoint: str | None
    bucket: str | None
    access_key_id: str | None
    secret_access_key: str | None


def build_object_store(
    kind: str,
    *,
    env: str,
    filesystem_root: Path | None = None,
    r2: R2Config | None = None,
) -> ObjectStore:
    """Select a store. The fake and filesystem stores are refused when ``env`` is production.

    Raises ``ValueError`` naming the missing setting, never its value.
    """
    if env == "production" and kind != "r2":
        raise ValueError(
            f"KS_OBJECT_STORE={kind!r} is not allowed when KS_ENV=production; "
            "set KS_OBJECT_STORE=r2"
        )
    if kind == "r2":
        missing = [
            name
            for name, value in (
                ("KS_R2_ENDPOINT", r2.endpoint if r2 else None),
                ("KS_R2_BUCKET", r2.bucket if r2 else None),
                ("KS_R2_ACCESS_KEY_ID", r2.access_key_id if r2 else None),
                ("KS_R2_SECRET_ACCESS_KEY", r2.secret_access_key if r2 else None),
            )
            if not value
        ]
        if r2 is None or not r2.endpoint or not r2.bucket:
            raise ValueError(f"KS_OBJECT_STORE=r2 needs {', '.join(missing)}")
        if not r2.access_key_id or not r2.secret_access_key:
            raise ValueError(f"KS_OBJECT_STORE=r2 needs {', '.join(missing)}")
        if not r2.endpoint.startswith("https://"):
            raise ValueError("KS_R2_ENDPOINT must be an https URL")
        return R2ObjectStore(
            endpoint=r2.endpoint,
            bucket=r2.bucket,
            access_key_id=r2.access_key_id,
            secret_access_key=r2.secret_access_key,
        )
    if kind == "filesystem":
        if filesystem_root is None:
            raise ValueError("KS_OBJECT_STORE_PATH is required for the filesystem store")
        return FilesystemObjectStore(filesystem_root)
    if kind == "fake":
        return FakeObjectStore()
    raise ValueError(f"Unknown KS_OBJECT_STORE {kind!r}")
