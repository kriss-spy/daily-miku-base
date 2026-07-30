"""Tests for the injectable v2 FastAPI shell."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from daily_miku.config import Settings
from daily_miku.content_source import (
    ContentFailure,
    InMemoryContentSource,
    ScanStatus,
    TaggedItem,
)
from daily_miku.domain import FixedClock
from daily_miku.http import create_app
from daily_miku.logging_config import JSONFormatter
from daily_miku.services import build_services

pytestmark = pytest.mark.unit


def slot_client(*, lookup_failure: ContentFailure | None = None) -> TestClient:
    """Build a complete isolated Slot API fixture."""
    settings = Settings.in_memory()
    observed_at = datetime(2026, 7, 16, 16, 3, tzinfo=timezone.utc)
    source = InMemoryContentSource(
        (
            TaggedItem(
                3,
                last_update=observed_at,
                source_url="https://example.com/three",
                title="Three",
                excerpt="Description",
                domain="example.com",
                tags=("daily-miku-2026-07-17",),
            ),
            TaggedItem(
                8,
                source_url="https://example.com/eight",
                title="Eight",
                tags=("daily-miku-2026-07-18",),
            ),
            TaggedItem(
                9,
                source_url="https://example.com/nine",
                title="Nine",
                tags=("daily-miku-2026-07-18",),
            ),
        ),
        lookup_failure=lookup_failure,
    )
    services = build_services(
        settings,
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        content_source=source,
    )
    return TestClient(create_app(services=services))


def test_composition_root_builds_an_in_memory_http_graph() -> None:
    settings = Settings.in_memory()
    services = build_services(settings)
    app = create_app(settings, services)

    assert app.state.services is services
    assert app.state.services.calendar.timezone.key == "Asia/Shanghai"


def test_composition_root_has_no_selection_ledger_services() -> None:
    services = build_services(Settings.in_memory())

    assert not hasattr(services, "ledger")
    assert not hasattr(services, "reconciler")
    assert not hasattr(services, "corrector")
    assert not hasattr(services, "initializer")


def test_app_uses_settings_from_an_injected_service_graph() -> None:
    services = build_services(Settings.in_memory())

    app = create_app(services=services)

    assert app.state.services is services


def test_every_request_has_correlated_safe_error_response() -> None:
    client = TestClient(create_app(Settings.in_memory()))

    first = client.get("/missing")
    second = client.get("/also-missing")

    assert first.status_code == 404
    assert first.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
            "details": {},
            "request_id": first.headers["X-Request-ID"],
        },
    }
    assert second.headers["X-Request-ID"] != first.headers["X-Request-ID"]


def test_structured_formatter_includes_request_id() -> None:
    import logging

    record = logging.LogRecord(
        "daily_miku.v2", logging.INFO, "", 0, "request_completed", (), None
    )
    record.request_id = "request-123"
    record.extra_fields = {"status_code": 404}

    document = json.loads(JSONFormatter().format(record))

    assert document["message"] == "request_completed"
    assert document["request_id"] == "request-123"
    assert document["status_code"] == 404


def test_request_validation_uses_the_common_error_envelope() -> None:
    app = create_app(Settings.in_memory())

    @app.get("/validate/{number}")
    def validate(number: int) -> dict[str, int]:
        return {"number": number}

    response = TestClient(app).get("/validate/not-an-integer")

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "request_validation_failed",
        "message": "The request is invalid.",
        "details": {},
        "request_id": response.headers["X-Request-ID"],
    }


def test_dated_today_and_range_return_complete_shared_representations() -> None:
    client = slot_client()

    selected = client.get("/api/slots/2026-07-17")
    today = client.get("/api/slots/today")
    calendar_range = client.get(
        "/api/slots", params={"from": "2026-07-17", "to": "2026-07-19"}
    )

    assert (
        selected.status_code == today.status_code == calendar_range.status_code == 200
    )
    assert selected.json() == {
        "date": "2026-07-17",
        "state": "selected",
        "items": [
            {
                "raindrop_id": 3,
                "title": "Three",
                "excerpt": "Description",
                "source_url": "https://example.com/three",
                "image_url": "/image/2026-07-17",
                "domain": "example.com",
                "tags": ["daily-miku-2026-07-17"],
                "selection_tag": "daily-miku-2026-07-17",
            }
        ],
        "links": {
            "self": "/api/slots/2026-07-17",
            "previous": "/api/slots/2026-07-16",
            "next": "/api/slots/2026-07-18",
        },
    }
    assert today.json()["state"] == "empty"
    assert [item["state"] for item in calendar_range.json()["items"]] == [
        "selected",
        "conflict",
        "empty",
    ]
    assert calendar_range.json()["links"]["self"] == (
        "/api/slots?from=2026-07-17&to=2026-07-19"
    )
    assert "s-maxage" in selected.headers["Cache-Control"]
    assert selected.headers["ETag"].startswith('"')
    assert calendar_range.headers["ETag"].startswith('"')


def test_latest_includes_conflict_and_random_excludes_it() -> None:
    client = slot_client()

    latest = client.get("/api/slots/latest")
    random = client.get("/api/slots/random")

    assert latest.status_code == random.status_code == 200
    assert latest.json()["state"] == "conflict"
    assert [item["raindrop_id"] for item in latest.json()["items"]] == [8, 9]
    assert random.json()["date"] == "2026-07-17"
    assert random.json()["state"] == "selected"
    assert random.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        ("/api/slots/not-a-date", 400, "date_malformed"),
        ("/api/slots/2026-02-30", 400, "date_malformed"),
        ("/api/slots/2026-07-20", 422, "future_selection_day"),
        ("/api/slots?from=2026-07-17", 400, "range_invalid"),
        ("/api/slots?from=nope&to=2026-07-19", 400, "date_malformed"),
        ("/api/slots?from=2026-07-19&to=2026-07-18", 400, "range_invalid"),
        ("/api/slots?from=2025-07-18&to=2026-07-19", 400, "range_invalid"),
        ("/api/slots?from=2026-07-19&to=2026-07-20", 422, "future_selection_day"),
    ],
)
def test_slot_validation_has_exact_status_and_safe_envelope(
    url: str, status: int, code: str
) -> None:
    response = slot_client().get(url)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"] == {}
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_selector_absence_remains_distinct_from_dependency_failure() -> None:
    empty_services = build_services(
        Settings.in_memory(),
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        content_source=InMemoryContentSource(),
    )
    no_result = TestClient(create_app(services=empty_services)).get("/api/slots/latest")
    random_no_result = TestClient(create_app(services=empty_services)).get(
        "/api/slots/random"
    )
    assert no_result.status_code == 404
    assert no_result.json()["error"]["code"] == "slot_not_found"
    assert random_no_result.status_code == 404
    assert random_no_result.json()["error"]["code"] == "slot_not_found"


def test_slot_resolution_does_not_require_the_legacy_ledger() -> None:
    services = build_services(
        Settings.in_memory(),
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        content_source=InMemoryContentSource(),
    )

    response = TestClient(create_app(services=services)).get("/api/slots/2026-07-19")

    assert response.status_code == 200
    assert response.json()["state"] == "empty"


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (ContentFailure.UPSTREAM, 502, "content_upstream_failed"),
        (ContentFailure.UNAVAILABLE, 503, "content_unavailable"),
        (ContentFailure.TIMEOUT, 504, "content_timeout"),
    ],
)
def test_content_dependency_failure_classes_are_distinct(
    failure: ContentFailure, status: int, code: str
) -> None:
    dependency = slot_client(lookup_failure=failure).get("/api/slots/2026-07-17")

    assert dependency.status_code == status
    assert dependency.json()["error"]["code"] == code
    assert dependency.headers["Cache-Control"] == "no-store"


def test_html_routes_render_selected_slot_and_calendar_navigation() -> None:
    client = slot_client()

    selected = client.get("/2026-07-17")
    redirected = client.get("/today", follow_redirects=False)

    assert selected.status_code == 200
    assert selected.headers["content-type"].startswith("text/html")
    assert '<main class="slot-page slot-page--selected"' in selected.text
    assert 'src="/image/2026-07-17"' in selected.text
    assert 'alt="Three"' in selected.text
    assert "Description" in selected.text
    assert "Raindrop ID" in selected.text and ">3<" in selected.text
    assert "daily-miku-2026-07-17" in selected.text
    assert "Recording method" not in selected.text
    assert 'href="/2026-07-16"' in selected.text
    assert 'href="/2026-07-18"' in selected.text
    assert 'aria-current="date"' in selected.text
    assert redirected.status_code == 307
    assert redirected.headers["location"] == "/"


def test_home_empty_and_dated_conflict_are_deliberate_html_states() -> None:
    client = slot_client()

    empty = client.get("/")
    conflict = client.get("/2026-07-18")

    assert empty.status_code == conflict.status_code == 200
    assert "Nothing was selected" in empty.text
    assert "This date remains open" in empty.text
    assert 'class="open-frame"' in empty.text
    assert "Selection conflict" in conflict.text
    assert "Multiple Daily Mikus occupy this date" in conflict.text
    assert "Eight" in conflict.text and "Nine" in conflict.text
    assert conflict.text.count("Raindrop ID") == 2
    assert '<ul class="candidate-list">' in conflict.text


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        ("/2026-7-20", 400, "date_malformed"),
        ("/2026-02-30", 400, "date_malformed"),
        ("/2026-07-20", 422, "future_selection_day"),
    ],
)
def test_html_date_validation_preserves_safe_failures(
    url: str, status: int, code: str
) -> None:
    response = slot_client().get(url)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_html_dependency_failure_is_not_rendered_as_empty() -> None:
    response = slot_client(lookup_failure=ContentFailure.UNAVAILABLE).get("/2026-07-17")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "content_unavailable"
    assert response.headers["Cache-Control"] == "no-store"


def test_editorial_stylesheet_has_responsive_and_accessible_invariants() -> None:
    css = slot_client().get("/static/editorial.css")

    assert css.status_code == 200
    assert "overflow-x: hidden" in css.text
    assert "@media (max-width: 48rem)" in css.text
    assert "@media (prefers-reduced-motion: reduce)" in css.text
    assert ":focus-visible" in css.text


def test_search_groups_complete_conflict_and_paginates_opaque_results() -> None:
    client = slot_client()

    conflict = client.get("/api/search", params={"q": "Eight"})
    first = client.get("/api/search", params={"q": "e", "limit": 1})
    second = client.get(
        "/api/search",
        params={"q": "e", "limit": 1, "cursor": first.json()["next_cursor"]},
    )

    assert conflict.status_code == 200
    assert conflict.json()["items"][0]["state"] == "conflict"
    assert [item["raindrop_id"] for item in conflict.json()["items"][0]["items"]] == [
        8,
        9,
    ]
    assert len(first.json()["items"]) == len(second.json()["items"]) == 1
    assert first.json()["next_cursor"]
    assert first.json()["links"]["next"]
    encoded = client.get("/api/search", params={"q": "Three & Nine"})
    assert "q=Three+%26+Nine" in encoded.json()["links"]["self"]


def test_search_html_is_complete_for_results_and_empty_state() -> None:
    client = slot_client()

    conflict = client.get("/search", params={"q": "Eight"})
    empty = client.get("/search", params={"q": "absent phrase"})

    assert conflict.status_code == empty.status_code == 200
    assert "Eight" in conflict.text and "Nine" in conflict.text
    assert 'href="/2026-07-18"' in conflict.text
    assert "No Daily Slots match this search" in empty.text
    assert '<form action="/search" method="get"' in empty.text


def test_statistics_support_explicit_and_unbounded_default_intervals() -> None:
    client = slot_client()

    bounded = client.get(
        "/api/statistics", params={"from": "2026-07-17", "to": "2026-07-19"}
    )
    long_period = client.get(
        "/api/statistics", params={"from": "2025-01-01", "to": "2026-07-19"}
    )
    default = client.get("/api/statistics")

    assert bounded.json() == {
        "from": "2026-07-17",
        "to": "2026-07-19",
        "calendar_days": 3,
        "selected_slots": 1,
        "empty_slots": 1,
        "conflict_slots": 1,
        "candidates": 3,
    }
    assert long_period.status_code == 200
    assert long_period.json()["calendar_days"] > 366
    assert default.json()["from"] == "2026-07-17"


@pytest.mark.parametrize(
    "url",
    [
        "/api/search?q=",
        "/api/search?q=Three&cursor=bad",
        "/api/search?q=Three&cursor=%25%25%25%25",
        "/api/search?q=Three&limit=101",
        "/api/statistics?from=2026-07-17",
        "/api/statistics?from=bad&to=2026-07-19",
    ],
)
def test_search_and_statistics_reject_malformed_requests(url: str) -> None:
    response = slot_client().get(url)

    assert response.status_code == 400


def test_archive_api_and_html_keep_complete_conflicts_newest_first() -> None:
    client = slot_client()

    first = client.get("/api/archive", params={"limit": 1})
    second = client.get(
        "/api/archive",
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )
    html = client.get("/archive")

    assert first.json()["items"][0]["date"] == "2026-07-18"
    assert first.json()["items"][0]["state"] == "conflict"
    assert len(first.json()["items"][0]["items"]) == 2
    assert second.json()["items"][0]["date"] == "2026-07-17"
    assert first.json()["links"]["next"]
    assert html.status_code == 200
    assert "Unresolved conflict · 2 candidates" in html.text
    assert 'href="/2026-07-18"' in html.text
    assert "archive-grid" in html.text

    context = client.get("/archive", params={"from": "2026-07-17", "to": "2026-07-19"})
    assert "2026-07-19 · empty" in context.text
    assert "2026-07-18 · conflict" in context.text


@pytest.mark.parametrize(
    "url",
    ["/api/archive?limit=0", "/api/archive?limit=101", "/api/archive?cursor=bad"],
)
def test_archive_rejects_invalid_limits_and_cursors(url: str) -> None:
    response = slot_client().get(url)

    assert response.status_code == 400


def test_reconciliation_endpoints_are_removed() -> None:
    client = slot_client()

    assert client.post("/internal/reconcile").status_code == 404
    assert client.get("/internal/reconciliation-status").status_code == 404


def test_multi_date_assignment_has_exact_409_contract() -> None:
    settings = Settings.in_memory()
    source = InMemoryContentSource(
        (
            TaggedItem(
                7,
                tags=("daily-miku-2026-07-17", "daily-miku-2026-07-18"),
            ),
        )
    )
    services = build_services(
        settings,
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        content_source=source,
    )

    client = TestClient(create_app(services=services))
    response = client.get("/api/slots/2026-07-17")
    image = client.get("/image/2026-07-17")
    statistics = client.get(
        "/api/statistics", params={"from": "2026-07-17", "to": "2026-07-19"}
    )

    assert response.status_code == image.status_code == statistics.status_code == 409
    assert response.json()["error"]["code"] == "multi_date_assignment"
    assert response.json()["error"]["details"]["assignments"] == [
        {
            "raindrop_id": 7,
            "selection_tags": [
                "daily-miku-2026-07-17",
                "daily-miku-2026-07-18",
            ],
        }
    ]
    assert response.headers["Cache-Control"] == "no-store"


def test_statistics_maps_incomplete_snapshot_failure() -> None:
    services = build_services(
        Settings.in_memory(),
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        in_memory=True,
        content_source=InMemoryContentSource(status=ScanStatus.INCOMPLETE),
    )

    response = TestClient(create_app(services=services)).get("/api/statistics")

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "content_upstream_failed"
