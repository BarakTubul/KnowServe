"""QStash publishing and delivery-signature verification (ING-13, SEC-14).

NOT VERIFIED AGAINST A LIVE QSTASH. The publish request shape (``POST {qstash_url}/v2/publish/
{destination}`` with a bearer token and ``Upstash-Forward-*`` headers) and the signature scheme
(``Upstash-Signature`` JWT, HS256, claims ``iss``/``sub``/``exp``/``nbf``/``body``) are implemented
from Upstash's public documentation. Live verification is BLOCKED until an approved cloud/QStash
account exists. Tests use fakes and locally signed tokens, which do not prove live behavior.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import uuid
from collections.abc import Sequence
from typing import Protocol

import httpx
import jwt

logger = logging.getLogger("knowserve.qstash")

SIGNATURE_HEADER = "Upstash-Signature"
CORRELATION_HEADER = "X-Correlation-ID"
ENVELOPE_SCHEMA_VERSION = 1
_LEEWAY_SECONDS = 5


class PublishError(Exception):
    """A publish attempt failed. The message never contains credentials."""


class SignatureError(Exception):
    """A delivery signature was missing or invalid. Never carries token material."""


def build_envelope(job_id: uuid.UUID) -> dict[str, object]:
    return {"schema_version": ENVELOPE_SCHEMA_VERSION, "job_id": str(job_id)}


class Publisher(Protocol):
    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        """Publish one job envelope. Raise ``PublishError`` on failure."""
        ...


class HttpPublisher:
    """Publishes through the QStash HTTP API (unverified against live QStash, see module doc)."""

    def __init__(
        self,
        qstash_url: str,
        token: str,
        destination_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base = qstash_url.rstrip("/")
        self._token = token
        self._destination = destination_url.rstrip("/") + "/internal/jobs/run"
        self._transport = transport
        self._timeout = timeout

    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        url = f"{self._base}/v2/publish/{self._destination}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            f"Upstash-Forward-{CORRELATION_HEADER}": correlation_id,
        }
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as c:
                response = await c.post(url, headers=headers, json=build_envelope(job_id))
        except httpx.HTTPError as exc:
            raise PublishError(f"QStash request failed: {type(exc).__name__}") from None
        if response.status_code >= 300:
            raise PublishError(f"QStash rejected the publish with status {response.status_code}")


class UnconfiguredPublisher:
    """Used when QStash settings are absent (local without a token): every publish fails."""

    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        raise PublishError("QStash publisher is not configured")


class FakePublisher:
    """In-memory publisher for tests (TEST-09)."""

    def __init__(self, fail: bool = False, delay: float = 0.0) -> None:
        self.published: list[tuple[uuid.UUID, str]] = []
        self.fail = fail
        self.delay = delay

    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise PublishError("fake publisher failure")
        self.published.append((job_id, correlation_id))


def _b64url_sha256(body: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip("=")


def verify_signature(
    *,
    token: str | None,
    body: bytes,
    signing_keys: Sequence[str],
    expected_url: str | None = None,
) -> None:
    """Verify an ``Upstash-Signature`` JWT. Raises ``SignatureError`` unless valid.

    Tries each key in order (current, then next). Requires ``iss == "Upstash"``, ``exp`` and
    ``nbf`` (small leeway), a ``body`` claim equal to base64url(SHA-256(raw body)) compared in
    constant time, and, when ``expected_url`` is given, ``sub`` equal to it.
    """
    if not token or not signing_keys:
        raise SignatureError("missing signature or keys")
    claims: dict[str, object] | None = None
    for key in signing_keys:
        if not key:
            continue
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["HS256"],
                issuer="Upstash",
                leeway=_LEEWAY_SECONDS,
                options={"require": ["iss", "exp", "nbf"]},
            )
            break
        except jwt.PyJWTError:
            continue
    if claims is None:
        raise SignatureError("invalid signature")
    claimed_body = claims.get("body")
    if not isinstance(claimed_body, str):
        raise SignatureError("missing body hash")
    expected_body = _b64url_sha256(body)
    if not hmac.compare_digest(claimed_body.rstrip("=").encode(), expected_body.encode()):
        raise SignatureError("body hash mismatch")
    if expected_url is not None:
        sub = claims.get("sub")
        if not isinstance(sub, str) or not hmac.compare_digest(
            sub.rstrip("/").encode(), expected_url.rstrip("/").encode()
        ):
            raise SignatureError("destination mismatch")
