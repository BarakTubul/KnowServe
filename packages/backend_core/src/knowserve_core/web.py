"""Shared FastAPI plumbing: request-id middleware and the standard error envelope (ARCH-05)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import request_context

logger = logging.getLogger("knowserve.web")
REQUEST_ID_HEADER = "X-Request-ID"


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Raise for expected, client-visible errors. ``code`` is a stable UPPER_SNAKE identifier."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


_STATUS_CODES = {
    401: ("UNAUTHENTICATED", "Authentication required"),
    403: ("FORBIDDEN", "Forbidden"),
    404: ("NOT_FOUND", "Resource not found"),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed"),
    409: ("CONFLICT", "Conflict"),
    503: ("DEPENDENCY_UNAVAILABLE", "A required service is unavailable"),
}


def error_response(
    status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    request_id = request_context.get_request_id() or request_context.new_request_id()
    body = ErrorEnvelope(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=details)
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers={REQUEST_ID_HEADER: request_id},
    )


def install_web(app: FastAPI) -> None:
    """Install the request-id middleware and the error handlers on a FastAPI app."""

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request_context.accept_or_new_request_id(
            request.headers.get(REQUEST_ID_HEADER)
        )
        request_context.clear()
        request_context.set_request_id(request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _STATUS_CODES.get(exc.status_code, ("HTTP_ERROR", "Request failed"))
        return error_response(exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(part) for part in err["loc"]], "msg": err["msg"], "type": err["type"]}
            for err in exc.errors()
        ]
        return error_response(422, "VALIDATION_ERROR", "Invalid request data", details)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled exception", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Internal server error")
