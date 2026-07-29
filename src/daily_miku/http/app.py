"""FastAPI application factory for Daily Miku v2."""

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode

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
from ..ledger.migrations import expected_schema_version
from ..images import ImageResolutionKind
from ..reliability import RateLimiter
from ..selections import MultiDateAssignment
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
    app.state.rate_limiter = RateLimiter()
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
            route_class = (
                "internal" if request.url.path.startswith("/internal/") else "public"
            )
            client = request.client.host if request.client else "unknown"
            retry_after = app.state.rate_limiter.retry_after(client, route_class)
            if retry_after is not None:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limited",
                            "message": "Request rate limit exceeded.",
                            "details": {},
                            "request_id": request_id,
                        }
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "Cache-Control": "no-store",
                        "X-Request-ID": request_id,
                    },
                )
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

    def multi_date_response(
        request: Request, exc: MultiDateAssignment
    ) -> JSONResponse:
        return error_response(
            request,
            409,
            "multi_date_assignment",
            message=str(exc),
            details={
                "date": exc.day.value.isoformat(),
                "assignments": [
                    {
                        "raindrop_id": assignment.raindrop_id,
                        "selection_tags": list(assignment.selection_tags),
                    }
                    for assignment in exc.assignments
                ],
            },
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
        except MultiDateAssignment as exc:
            return multi_date_response(request, exc)
        except ContentDependencyError as exc:
            return content_error_response(request, exc)

    @app.get("/health")
    def health() -> JSONResponse:
        return json_response({"status": "ok"}, "no-store", validator=False)

    @app.get("/ready")
    def readiness(request: Request) -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            checks["schema"] = (
                "ok"
                if resolved_services.schema_version()
                == expected_schema_version()
                else "failed"
            )
        except Exception:
            checks["schema"] = "failed"
        try:
            scan = resolved_services.content_source.scan_tagged()
            checks["raindrop"] = "ok" if scan.status.value == "complete" else "failed"
        except ContentDependencyError:
            checks["raindrop"] = "failed"
        if all(value == "ok" for value in checks.values()):
            return json_response(
                {"status": "ready", "checks": checks}, "no-store", validator=False
            )
        return error_response(
            request,
            503,
            "not_ready",
            message="Required deployment dependencies are not ready.",
            details={"checks": checks},
            headers={"Cache-Control": "no-store"},
        )

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
        except MultiDateAssignment as exc:
            return multi_date_response(request, exc)
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
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        today = resolved_services.calendar.today(resolved_services.clock)
        parameters = {"q": query, "limit": str(limit)}
        if cursor:
            parameters["cursor"] = cursor
        self_link = f"/api/search?{urlencode(parameters)}"
        next_link = (
            f"/api/search?{urlencode({'q': query, 'limit': str(limit), 'cursor': page.next_cursor})}"
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

    @app.get("/api/archive")
    def archive_api(request: Request) -> JSONResponse:
        cursor = request.query_params.get("cursor")
        try:
            limit = int(request.query_params.get("limit", "24"))
            page = resolved_services.catalog.archive(cursor=cursor, limit=limit)
        except (ValueError, InvalidCursor) as exc:
            return error_response(request, 400, "archive_invalid", message=str(exc))
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        today = resolved_services.calendar.today(resolved_services.clock)
        self_link = f"/api/archive?limit={limit}"
        if cursor:
            self_link += f"&cursor={cursor}"
        next_link = (
            f"/api/archive?limit={limit}&cursor={page.next_cursor}"
            if page.next_cursor
            else None
        )
        return json_response(
            {
                "items": [slot_document(slot, today) for slot in page.items],
                "next_cursor": page.next_cursor,
                "links": {"self": self_link, "next": next_link},
            },
            "public, max-age=30, s-maxage=60",
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
        except MultiDateAssignment as exc:
            return multi_date_response(request, exc)
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
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
        except MultiDateAssignment as exc:
            return multi_date_response(request, exc)

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

    def render_slot(request: Request, day: date) -> Response:
        try:
            slot = resolved_services.catalog.get_slot(day)
            today = resolved_services.calendar.today(resolved_services.clock).value
            rail_start = day - timedelta(days=min(3, day.toordinal() - 1))
            rail_end = min(day + timedelta(days=3), today)
            rail = []
            rail_day = rail_start
            while rail_day <= rail_end:
                try:
                    rail.append(resolved_services.catalog.get_slot(rail_day))
                except MultiDateAssignment:
                    pass
                rail_day += timedelta(days=1)
        except FutureSelectionDay as exc:
            return error_response(
                request, 422, "future_selection_day", message=str(exc)
            )
        except MultiDateAssignment as exc:
            return multi_date_response(request, exc)
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
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        return templates.TemplateResponse(
            request, "search.html", {"query": query, "page": page}
        )

    @app.get("/archive", response_class=HTMLResponse)
    def archive_page(request: Request) -> Response:
        cursor = request.query_params.get("cursor")
        context = None
        try:
            page = resolved_services.catalog.archive(cursor=cursor)
            first_value = request.query_params.get("from")
            last_value = request.query_params.get("to")
            if (first_value is None) != (last_value is None):
                raise SlotRequestError(
                    400, "range_invalid", "Both from and to are required."
                )
            if first_value and last_value:
                context = resolved_services.catalog.range(
                    parse_date(first_value, "from"), parse_date(last_value, "to")
                )
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
        except InvalidCursor as exc:
            return error_response(request, 400, "archive_invalid", message=str(exc))
        except MultiDateAssignment as exc:
            return multi_date_response(request, exc)
        except ContentDependencyError as exc:
            return content_error_response(request, exc)
        return templates.TemplateResponse(
            request, "archive.html", {"page": page, "context": context}
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
