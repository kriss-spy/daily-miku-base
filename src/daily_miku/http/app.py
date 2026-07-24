"""FastAPI application factory for Daily Miku v2."""

import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..catalog import (
    CatalogSlot,
    InvalidCursor,
    InvalidSlotRange,
    SlotNotFound,
    slot_document,
)
from ..config import Settings
from ..content_source import ContentDependencyError, ContentFailure
from ..domain import FutureSelectionDay
from ..logging_config import (
    generate_request_id,
    reset_request_id,
    set_request_id,
    setup_logging,
)
from ..ledger.port import LedgerDependencyError, RunStatus
from ..images import ImageResolutionKind
from ..reconcile import ReconciliationDependencyError
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
    package_root = Path(__file__).resolve().parent.parent
    templates = Jinja2Templates(directory=package_root / "templates_v2")
    app.mount(
        "/static",
        StaticFiles(directory=package_root / "static"),
        name="static",
    )

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

    def error_response(
        request: Request,
        status_code: int,
        code: str,
        *,
        message: str | None = None,
        details: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> JSONResponse:
        request_id = request.state.request_id
        response_headers = {"X-Request-ID": request_id}
        response_headers.update(headers or {})
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": message or _safe_message(status_code),
                    "details": details or {},
                    "request_id": request_id,
                },
            },
            headers=response_headers,
        )

    def parse_date(value: str, field_name: str = "date") -> date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise SlotRequestError(
                400, "date_malformed", f"{field_name} must be YYYY-MM-DD."
            )
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise SlotRequestError(
                400, "date_malformed", f"{field_name} must be YYYY-MM-DD."
            ) from exc

    def json_response(
        content: object, cache_control: str, *, validator: bool = True
    ) -> JSONResponse:
        response = JSONResponse(content, headers={"Cache-Control": cache_control})
        if validator:
            response.headers["ETag"] = f'"{sha256(response.body).hexdigest()}"'
        return response

    def content_error_response(
        request: Request, exc: ContentDependencyError
    ) -> JSONResponse:
        status_code, code = {
            ContentFailure.UPSTREAM: (502, "content_upstream_failed"),
            ContentFailure.UNAVAILABLE: (503, "content_unavailable"),
            ContentFailure.TIMEOUT: (504, "content_timeout"),
        }[exc.kind]
        return error_response(
            request,
            status_code,
            code,
            message=str(exc),
            headers={"Cache-Control": "no-store"},
        )

    def slot_response(slot: CatalogSlot, cache_control: str) -> JSONResponse:
        document = slot_document(
            slot,
            resolved_services.calendar.today(resolved_services.clock),
        )
        return json_response(
            document, cache_control, validator=cache_control != "no-store"
        )

    def read_slot(
        request: Request, operation: Callable[[], CatalogSlot], cache: str
    ) -> JSONResponse:
        try:
            return slot_response(operation(), cache)
        except FutureSelectionDay as exc:
            return error_response(
                request, 422, "future_selection_day", message=str(exc)
            )
        except SlotNotFound as exc:
            return error_response(
                request,
                404,
                "slot_not_found",
                message=str(exc),
                headers={"Cache-Control": "public, max-age=15"},
            )
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "ledger_unavailable",
                message="The Selection Ledger is temporarily unavailable.",
                headers={"Cache-Control": "no-store"},
            )
        except ContentDependencyError as exc:
            return content_error_response(request, exc)

    @app.get("/api/slots/today")
    def get_today(request: Request) -> JSONResponse:
        return read_slot(
            request,
            resolved_services.catalog.today,
            "public, max-age=15, s-maxage=15",
        )

    @app.get("/api/slots/latest")
    def get_latest(request: Request) -> JSONResponse:
        return read_slot(
            request,
            resolved_services.catalog.latest,
            "public, max-age=15, s-maxage=30",
        )

    @app.get("/api/slots/random")
    def get_random(request: Request) -> JSONResponse:
        return read_slot(request, resolved_services.catalog.random, "no-store")

    @app.get("/api/slots")
    def get_range(request: Request) -> JSONResponse:
        first_value = request.query_params.get("from")
        last_value = request.query_params.get("to")
        if first_value is None or last_value is None:
            return error_response(
                request,
                400,
                "range_invalid",
                message="Both from and to are required.",
            )
        try:
            first = parse_date(first_value, "from")
            last = parse_date(last_value, "to")
            slots = resolved_services.catalog.range(first, last)
        except SlotRequestError as exc:
            return error_response(
                request, exc.status_code, exc.code, message=exc.message
            )
        except InvalidSlotRange as exc:
            return error_response(request, 400, "range_invalid", message=str(exc))
        except FutureSelectionDay as exc:
            return error_response(
                request, 422, "future_selection_day", message=str(exc)
            )
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "ledger_unavailable",
                message="The Selection Ledger is temporarily unavailable.",
                headers={"Cache-Control": "no-store"},
            )
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        today = resolved_services.calendar.today(resolved_services.clock)
        return json_response(
            {
                "items": [slot_document(slot, today) for slot in slots],
                "links": {
                    "self": f"/api/slots?from={first.isoformat()}&to={last.isoformat()}"
                },
            },
            "public, max-age=30, s-maxage=60",
        )

    @app.get("/api/slots/{date_value}")
    def get_dated_slot(request: Request, date_value: str) -> JSONResponse:
        try:
            day = parse_date(date_value)
        except SlotRequestError as exc:
            return error_response(
                request, exc.status_code, exc.code, message=exc.message
            )
        return read_slot(
            request,
            lambda: resolved_services.catalog.get_slot(day),
            "public, max-age=30, s-maxage=60",
        )

    @app.get("/api/search")
    def search_api(request: Request) -> JSONResponse:
        query = request.query_params.get("q", "")
        cursor = request.query_params.get("cursor")
        try:
            limit = int(request.query_params.get("limit", "24"))
            page = resolved_services.catalog.search(query, cursor=cursor, limit=limit)
        except (ValueError, InvalidCursor) as exc:
            return error_response(request, 400, "search_invalid", message=str(exc))
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "ledger_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        today = resolved_services.calendar.today(resolved_services.clock)
        self_link = f"/api/search?q={query}&limit={limit}"
        if cursor:
            self_link += f"&cursor={cursor}"
        next_link = (
            f"/api/search?q={query}&limit={limit}&cursor={page.next_cursor}"
            if page.next_cursor
            else None
        )
        return json_response(
            {
                "items": [slot_document(slot, today) for slot in page.items],
                "next_cursor": page.next_cursor,
                "links": {"self": self_link, "next": next_link},
            },
            "public, max-age=15, s-maxage=30",
        )

    @app.get("/api/statistics")
    def statistics_api(request: Request) -> JSONResponse:
        first_value = request.query_params.get("from")
        last_value = request.query_params.get("to")
        if (first_value is None) != (last_value is None):
            return error_response(
                request, 400, "range_invalid", message="Both from and to are required."
            )
        try:
            first = parse_date(first_value, "from") if first_value else None
            last = parse_date(last_value, "to") if last_value else None
            statistics = resolved_services.catalog.statistics(first, last)
        except SlotRequestError as exc:
            return error_response(
                request, exc.status_code, exc.code, message=exc.message
            )
        except InvalidSlotRange as exc:
            return error_response(request, 400, "range_invalid", message=str(exc))
        except FutureSelectionDay as exc:
            return error_response(
                request, 422, "future_selection_day", message=str(exc)
            )
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "ledger_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        return json_response(statistics.as_dict(), "public, max-age=30, s-maxage=60")

    @app.get("/image/{date_value}")
    def get_dated_image(request: Request, date_value: str) -> Response:
        """Resolve a mutable date to validated immutable controlled content."""
        try:
            day = parse_date(date_value)
            resolution = resolved_services.images.resolve_image(day)
        except SlotRequestError as exc:
            return error_response(
                request,
                exc.status_code,
                exc.code,
                message=exc.message,
                headers={"Cache-Control": "no-store"},
            )
        except FutureSelectionDay as exc:
            return error_response(
                request,
                422,
                "future_selection_day",
                message=str(exc),
                headers={"Cache-Control": "no-store"},
            )
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "image_unavailable",
                message="Image resolution is temporarily unavailable.",
                headers={"Cache-Control": "no-store"},
            )

        mutable_cache = "public, max-age=60, s-maxage=300"
        if resolution.kind is ImageResolutionKind.REDIRECT:
            response = RedirectResponse(resolution.location or "", status_code=307)
            response.headers["Cache-Control"] = mutable_cache
            response.headers["ETag"] = f'"sha256-{resolution.digest}"'
            return response
        status, code, message, cache = {
            ImageResolutionKind.NO_IMAGE: (
                404,
                "image_not_found",
                "No controlled image is available for this Daily Slot.",
                "public, max-age=15, s-maxage=30",
            ),
            ImageResolutionKind.CONFLICT: (
                409,
                "slot_conflict",
                "Multiple Daily Mikus occupy this slot.",
                mutable_cache,
            ),
            ImageResolutionKind.WITHDRAWN: (
                410,
                "image_withdrawn",
                "The image has been intentionally withdrawn.",
                mutable_cache,
            ),
            ImageResolutionKind.UPSTREAM: (
                502,
                "image_upstream_failed",
                "The image could not be validated from its upstream source.",
                "no-store",
            ),
            ImageResolutionKind.UNAVAILABLE: (
                503,
                "image_unavailable",
                "Image resolution is temporarily unavailable.",
                "no-store",
            ),
            ImageResolutionKind.TIMEOUT: (
                504,
                "image_timeout",
                "Image resolution timed out.",
                "no-store",
            ),
        }[resolution.kind]
        return error_response(
            request,
            status,
            code,
            message=message,
            headers={"Cache-Control": cache},
        )

    @app.post("/internal/reconcile")
    def reconcile(request: Request) -> JSONResponse:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        expected = resolved_settings.reconcile_secret.get_secret_value()
        if (
            not separator
            or scheme.lower() != "bearer"
            or not secrets.compare_digest(
                credential.encode("utf-8"), expected.encode("utf-8")
            )
        ):
            return error_response(
                request,
                401,
                "authentication_required",
                message="Valid bearer authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            report = resolved_services.reconciler.reconcile()
        except ReconciliationDependencyError:
            return error_response(
                request,
                503,
                "reconciliation_dependency_failed",
                message="Reconciliation could not access required storage.",
            )
        if report.status is not RunStatus.COMPLETE:
            return error_response(
                request,
                503,
                report.error_code or "reconciliation_failed",
                message=report.error_message,
                details={
                    "run_id": report.run_id,
                    "status": report.status.value,
                    "discovered": report.discovered_count,
                },
            )
        return JSONResponse(report.as_dict())

    def render_slot(request: Request, day: date) -> Response:
        try:
            slot = resolved_services.catalog.get_slot(day)
            today = resolved_services.calendar.today(resolved_services.clock).value
            rail_start = day - timedelta(days=min(3, day.toordinal() - 1))
            rail_end = min(day + timedelta(days=3), today)
            rail = resolved_services.catalog.range(rail_start, rail_end)
        except FutureSelectionDay as exc:
            return error_response(
                request, 422, "future_selection_day", message=str(exc)
            )
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "ledger_unavailable",
                message="The Selection Ledger is temporarily unavailable.",
                headers={"Cache-Control": "no-store"},
            )
        except ContentDependencyError as exc:
            return content_error_response(request, exc)

        previous = day - timedelta(days=1) if day > date.min else None
        next_day = day + timedelta(days=1) if day < today else None
        return templates.TemplateResponse(
            request,
            "slot.html",
            {
                "slot": slot,
                "rail": rail,
                "today": today,
                "previous": previous,
                "next": next_day,
            },
            headers={"Cache-Control": "public, max-age=30, s-maxage=60"},
        )

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Response:
        today = resolved_services.calendar.today(resolved_services.clock).value
        return render_slot(request, today)

    @app.get("/today", include_in_schema=False)
    def today_redirect() -> RedirectResponse:
        return RedirectResponse("/", status_code=307)

    @app.get("/search", response_class=HTMLResponse)
    def search_page(request: Request) -> Response:
        query = request.query_params.get("q", "")
        if not query.strip():
            return templates.TemplateResponse(
                request, "search.html", {"query": query, "page": None}
            )
        try:
            page = resolved_services.catalog.search(query)
        except LedgerDependencyError:
            return error_response(
                request,
                503,
                "ledger_unavailable",
                headers={"Cache-Control": "no-store"},
            )
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        return templates.TemplateResponse(
            request, "search.html", {"query": query, "page": page}
        )

    @app.get("/{date_value}", response_class=HTMLResponse)
    def dated_page(request: Request, date_value: str) -> Response:
        if not date_value[:1].isdigit():
            return error_response(request, 404, "not_found")
        try:
            day = parse_date(date_value)
        except SlotRequestError as exc:
            return error_response(
                request, exc.status_code, exc.code, message=exc.message
            )
        return render_slot(request, day)

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


class SlotRequestError(ValueError):
    """A safely renderable Slot request parsing failure."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
