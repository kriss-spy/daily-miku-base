"""Tests for health, freshness, and bounded route limits."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from daily_miku.config import Settings
from daily_miku.content_source import InMemoryContentSource, ScanStatus, TaggedItem
from daily_miku.domain import FixedClock
from daily_miku.http import create_app
from daily_miku.reliability import RateLimiter
from daily_miku.services import build_services

pytestmark = pytest.mark.unit


def reliability_client(
    *, source_status: ScanStatus = ScanStatus.COMPLETE
) -> TestClient:
    services = build_services(
        Settings.in_memory(),
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        in_memory=True,
        content_source=InMemoryContentSource(status=source_status),
    )
    return TestClient(create_app(services=services))


def test_health_is_live_while_readiness_exposes_safe_dependency_state() -> None:
    ready = reliability_client()
    unavailable = reliability_client(source_status=ScanStatus.INCOMPLETE)

    assert ready.get("/health").json() == {"status": "ok"}
    healthy = ready.get("/ready")
    failed = unavailable.get("/ready")

    assert healthy.status_code == 200
    assert healthy.json()["checks"] == {"schema": "ok", "raindrop": "ok"}
    assert failed.status_code == 503
    assert failed.json()["error"]["details"]["checks"]["raindrop"] == "failed"
    assert failed.headers["Cache-Control"] == "no-store"


def test_selection_snapshot_cache_reuses_one_bounded_account_scan() -> None:
    source = InMemoryContentSource(
        (TaggedItem(1, tags=("daily-miku-2026-07-19",)),)
    )
    services = build_services(
        Settings.in_memory(),
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        in_memory=True,
        content_source=source,
    )

    services.catalog.today()
    services.catalog.archive()
    services.catalog.statistics()

    assert source.scan_count == 1


def test_rate_limiter_has_retry_after_and_recovers_after_window() -> None:
    current = 0.0
    limiter = RateLimiter(public_limit=2, internal_limit=1, now=lambda: current)

    assert limiter.retry_after("client", "public") is None
    assert limiter.retry_after("client", "public") is None
    assert limiter.retry_after("client", "public") == 60
    assert limiter.retry_after("client", "internal") is None
    assert limiter.retry_after("client", "internal") == 60
    current = 61.0
    assert limiter.retry_after("client", "public") is None


def test_http_rate_limit_preserves_request_correlation() -> None:
    client = reliability_client()
    client.app.state.rate_limiter = RateLimiter(public_limit=1)

    assert client.get("/health").status_code == 200
    limited = client.get("/health")

    assert limited.status_code == 429
    assert limited.headers["Retry-After"]
    assert limited.json()["error"]["request_id"] == limited.headers["X-Request-ID"]
