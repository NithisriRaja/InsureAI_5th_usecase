"""Uniform error envelope: ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.utils.logging import get_logger

log = get_logger(__name__)


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str, ident: str) -> AppError:
    return AppError(404, "not_found", f"{what} {ident} not found")


def body(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app(_: Request, e: AppError) -> JSONResponse:
        return JSONResponse(body(e.code, e.message, e.details), status_code=e.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse(body(code, str(e.detail)), status_code=e.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]
        return JSONResponse(body("validation_error", "Invalid request", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception) -> JSONResponse:
        log.exception("api.unhandled", error=str(e))
        return JSONResponse(body("internal_error", "Internal server error"), status_code=500)
