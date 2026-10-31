"""Direct-access protection for the same-origin proxy design (contract: docs/contracts/proxy.md).

When ``KS_PROXY_SHARED_SECRET`` is set, every route except the two health probes must carry the
matching ``X-KS-Proxy-Secret`` header, which only the Pages Function adds. A request that reaches
the public ``run.app`` URL directly is rejected before any route code runs. The client IP the
proxy forwards is trusted only after the secret check passed.
"""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from knowserve_core.web import error_response

PROXY_SECRET_HEADER = "X-KS-Proxy-Secret"
CLIENT_IP_HEADER = "X-KS-Client-IP"
OPEN_PATHS = frozenset({"/health/live", "/health/ready"})


def parse_client_ip(value: str | None) -> str | None:
    """Return a normalized IP address, or None if the value is missing or not an IP."""
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def install_proxy_guard(app: FastAPI, secret: str) -> None:
    """Install the guard. Add it BEFORE ``install_web`` so error responses carry a request id."""
    expected = secret.encode()

    @app.middleware("http")
    async def proxy_guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in OPEN_PATHS:
            request.state.client_ip = None
            return await call_next(request)
        supplied = request.headers.get(PROXY_SECRET_HEADER, "").encode()
        if not hmac.compare_digest(supplied, expected):
            return error_response(403, "DIRECT_ACCESS_DENIED", "Direct access is not allowed")
        request.state.client_ip = parse_client_ip(request.headers.get(CLIENT_IP_HEADER))
        return await call_next(request)
