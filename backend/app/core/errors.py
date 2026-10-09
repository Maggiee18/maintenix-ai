"""Consistent error envelope: {"error": {"code", "message", "details", "request_id"}}.

Unhandled exceptions are logged with a stack trace server-side and returned as
a generic 500 without internals.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging import request_id_var

log = logging.getLogger("maintenix.errors")


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(AppError):
    status_code, code = status.HTTP_404_NOT_FOUND, "not_found"


class Conflict(AppError):
    status_code, code = status.HTTP_409_CONFLICT, "conflict"


class Forbidden(AppError):
    status_code, code = status.HTTP_403_FORBIDDEN, "forbidden"


class Unauthorized(AppError):
    status_code, code = status.HTTP_401_UNAUTHORIZED, "unauthorized"


class InvalidTransition(AppError):
    status_code, code = status.HTTP_409_CONFLICT, "invalid_transition"


class ValidationFailed(AppError):
    status_code, code = status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_failed"


class RateLimited(AppError):
    status_code, code = status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited"


class ServiceUnavailable(AppError):
    status_code, code = status.HTTP_503_SERVICE_UNAVAILABLE, "service_unavailable"


def _body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details, "request_id": request_id_var.get()}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, Unauthorized) else None
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(_body("validation_failed", "Request validation failed", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(_body("internal_error", "An unexpected error occurred"), status_code=500)
