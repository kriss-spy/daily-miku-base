"""FastAPI application factory for Daily Miku v2."""

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import Settings
from ..logging_config import (
    generate_request_id,
    reset_request_id,
    set_request_id,
    setup_logging,
)
from ..services import Services, build_services

logger = logging.getLogger("daily_miku.v2")


def create_app(
    settings: Settings | None = None, services: Services | None = None
) -> FastAPI:
    """Build a v2 app with either production or injected dependencies."""
    resolved_settings = settings or (
        services.settings if services is not None else Settings.from_environment()
    )
    resolved_services = services or build_services(resolved_settings)
    setup_logging()
    app = FastAPI(title="Daily Miku", version="2.0.0")
    app.state.services = resolved_services

    @app.middleware("http")
    async def correlate_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = generate_request_id()
        request.state.request_id = request_id
        token = set_request_id(request_id)
        logger.info(
            "request_started",
            extra={
                "request_id": request_id,
                "extra_fields": {"method": request.method, "path": request.url.path},
            },
        )
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "extra_fields": {"status_code": response.status_code},
                },
            )
            return response
        finally:
            reset_request_id(token)

    def error_response(request: Request, status_code: int, code: str) -> JSONResponse:
        request_id = request.state.request_id
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": _safe_message(status_code),
                    "details": {},
                    "request_id": request_id,
                },
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return error_response(request, exc.status_code, _error_code(exc.status_code))

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(request, 422, "request_validation_failed")

    @app.exception_handler(Exception)
    def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_request_error", extra={"request_id": request.state.request_id}
        )
        return error_response(request, 500, "internal_error")

    return app


def _error_code(status_code: int) -> str:
    if status_code == 404:
        return "not_found"
    return f"http_{status_code}"


def _safe_message(status_code: int) -> str:
    if status_code == 404:
        return "The requested resource was not found."
    if status_code >= 500:
        return "The request could not be completed."
    return "The request is invalid."
