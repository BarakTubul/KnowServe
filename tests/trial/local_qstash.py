"""A local stand-in for QStash, for the M3 local real-API trial only (never deployed).

It accepts the publish call the API makes (``POST /v2/publish/{destination}``), answers 200, then
delivers the same body to the destination with an ``Upstash-Signature`` JWT signed with the local
signing key, the way QStash does. On a 5xx answer it retries up to three more times with a short
delay. It does not model QStash's real backoff or headers; that is what the D15 experiment checks.

Run: ``KS_QSTASH_CURRENT_SIGNING_KEY=... uv run python tests/trial/local_qstash.py`` (port 8090).
The key and the destination are local-only values; nothing here talks to the internet.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
import uuid

import httpx
import jwt
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

SIGNING_KEY = os.environ.get(
    "KS_QSTASH_CURRENT_SIGNING_KEY", "local-only-qstash-current-key-not-a-secret"
)
PORT = int(os.environ.get("TRIAL_QSTASH_PORT", "8090"))
RETRY_DELAY_SECONDS = float(os.environ.get("TRIAL_QSTASH_RETRY_DELAY", "3"))
FORWARD_PREFIX = "upstash-forward-"
_tasks: set[asyncio.Task[None]] = set()


def _destination(raw_path: str) -> str:
    """``http:/host/x`` (a collapsed double slash) back to ``http://host/x``."""
    for scheme in ("http", "https"):
        if raw_path.startswith(f"{scheme}:/") and not raw_path.startswith(f"{scheme}://"):
            return f"{scheme}://" + raw_path[len(scheme) + 2 :]
    return raw_path


def _sign(body: bytes, url: str) -> str:
    now = int(time.time())
    claims = {
        "iss": "Upstash",
        "sub": url,
        "iat": now,
        "nbf": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
        "body": base64.urlsafe_b64encode(hashlib.sha256(body).digest()).decode().rstrip("="),
    }
    return jwt.encode(claims, SIGNING_KEY, algorithm="HS256")


async def _deliver(url: str, body: bytes, headers: dict[str, str]) -> None:
    for attempt in range(4):
        await asyncio.sleep(0.3 if attempt == 0 else RETRY_DELAY_SECONDS)
        send = {
            **headers,
            "Upstash-Signature": _sign(body, url),
            "Content-Type": "application/json",
        }
        send["Upstash-Retried"] = str(attempt)
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(url, content=body, headers=send)
        except httpx.HTTPError as exc:
            print(f"deliver {url} attempt {attempt}: {type(exc).__name__}", flush=True)
            continue
        print(f"deliver {url} attempt {attempt}: {response.status_code}", flush=True)
        if response.status_code < 300 or response.status_code in (409, 489):
            return


async def publish(request: Request) -> JSONResponse:
    destination = _destination(request.path_params["destination"])
    body = await request.body()
    forwarded = {
        key[len(FORWARD_PREFIX) :]: value
        for key, value in request.headers.items()
        if key.lower().startswith(FORWARD_PREFIX)
    }
    task = asyncio.create_task(_deliver(destination, body, forwarded))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return JSONResponse({"messageId": uuid.uuid4().hex})


app = Starlette(routes=[Route("/v2/publish/{destination:path}", publish, methods=["POST"])])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
