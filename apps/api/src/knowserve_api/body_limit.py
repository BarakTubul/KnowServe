"""Request body cap for the Admin write routes (SEC-11, M3 review finding).

FastAPI parses a multipart body before it resolves dependencies, so without a cap an
unauthenticated client could make the API parse and spool a large body before the 401. This pure
ASGI middleware answers first, without reading the body:

* no session cookie at all: 401 ``UNAUTHENTICATED`` immediately. This is only a cheap presence
  check. A forged or expired cookie value still gets past it, and is then bounded by the size cap
  below and rejected by the normal auth dependency (401/403).
* a cookie is present: 413 from ``Content-Length`` when it is present, and from a running byte
  count when it is absent or wrong.

Normal requests that carry a cookie pass through unchanged, so the order of the real auth checks
does not change.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from knowserve_core.ingestion_contract import AdminErrorCode, admin_error
from knowserve_core.web import error_response

GUARDED_PREFIX = "/v1/admin/"
GUARDED_METHODS = frozenset({"POST", "PATCH", "PUT"})
HEADROOM_BYTES = 64 * 1024  # multipart framing and the small form fields


class AdminBodyLimit:
    def __init__(self, app: ASGIApp, max_body_bytes: int, session_cookie_name: str) -> None:
        self.app = app
        self.cookie_prefix = session_cookie_name.encode() + b"="
        self.limit = max_body_bytes + HEADROOM_BYTES

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in GUARDED_METHODS
            or not scope["path"].startswith(GUARDED_PREFIX)
        ):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if not self._has_session_cookie(headers.get(b"cookie", b"")):
            response = error_response(
                401, "UNAUTHENTICATED", "Authentication required", headers={"Connection": "close"}
            )
            await response(scope, receive, send)
            return
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.limit
            except ValueError:
                too_big = True
            if too_big:
                await self._reject(scope, receive, send)
                return

        seen = 0
        exceeded = False

        async def counted_receive() -> Message:
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    exceeded = True
                    return {"type": "http.disconnect"}  # stop the parser; no more bytes are read
            return message

        async def guarded_send(message: Message) -> None:
            if exceeded:
                return  # the app is unwinding from the cut-off body; its answer is not wanted
            await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded:
            await self._reject(scope, receive, send)

    def _has_session_cookie(self, header: bytes) -> bool:
        return any(part.strip().startswith(self.cookie_prefix) for part in header.split(b";"))

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        status, code, message = admin_error(AdminErrorCode.FILE_TOO_LARGE)
        response = error_response(status, code, message, headers={"Connection": "close"})
        await response(scope, receive, send)
