"""Tests for the injectable v2 FastAPI shell."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from daily_miku.config import Settings
from daily_miku.content_source import InMemoryContentSource, ScanStatus, TaggedItem
from daily_miku.domain import FixedClock
from daily_miku.http import create_app
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.ledger.postgres import PostgresLedger
from daily_miku.logging_config import JSONFormatter
from daily_miku.services import build_services

pytestmark = pytest.mark.unit


def test_composition_root_builds_an_in_memory_http_graph() -> None:
    settings = Settings.in_memory()
    services = build_services(settings, ledger=InMemoryLedger())
    app = create_app(settings, services)

    assert app.state.services is services
    assert app.state.services.calendar.timezone.key == "Asia/Shanghai"


def test_composition_root_uses_durable_ledger_by_default() -> None:
    services = build_services(Settings.in_memory())

    assert isinstance(services.ledger, PostgresLedger)


def test_app_uses_settings_from_an_injected_service_graph() -> None:
    services = build_services(Settings.in_memory(), ledger=InMemoryLedger())

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


def test_internal_reconcile_requires_bearer_authentication() -> None:
    settings = Settings.in_memory()
    source = InMemoryContentSource((TaggedItem(7),))
    services = build_services(
        settings,
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        ledger=InMemoryLedger(),
        content_source=source,
    )
    client = TestClient(create_app(services=services))

    missing = client.post("/internal/reconcile")
    invalid = client.post(
        "/internal/reconcile", headers={"Authorization": "Bearer incorrect"}
    )
    non_ascii = client.post(
        "/internal/reconcile",
        headers=[(b"authorization", b"Bearer incorrect-\xe9")],
    )

    assert missing.status_code == invalid.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert missing.json()["error"]["code"] == "authentication_required"
    assert invalid.json()["error"]["code"] == "authentication_required"
    assert non_ascii.status_code == 401
    assert source.scan_count == 0


def test_internal_reconcile_invokes_shared_idempotent_service() -> None:
    settings = Settings.in_memory()
    source = InMemoryContentSource((TaggedItem(7), TaggedItem(9)))
    services = build_services(
        settings,
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        ledger=InMemoryLedger(),
        content_source=source,
    )
    client = TestClient(create_app(services=services))
    headers = {"Authorization": "Bearer not-a-real-secret"}

    first = client.post("/internal/reconcile", headers=headers)
    second = client.post("/internal/reconcile", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "run_id": 1,
        "status": "complete",
        "discovered": 2,
        "inserted": 2,
    }
    assert second.json()["inserted"] == 0
    assert services.reconciler.content_source is services.content_source
    assert services.reconciler.ledger is services.ledger


def test_internal_reconcile_exposes_incomplete_run_as_dependency_failure() -> None:
    settings = Settings.in_memory()
    source = InMemoryContentSource((TaggedItem(7),), status=ScanStatus.INCOMPLETE)
    services = build_services(
        settings,
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        ledger=InMemoryLedger(),
        content_source=source,
    )

    response = TestClient(create_app(services=services)).post(
        "/internal/reconcile",
        headers={"Authorization": "Bearer not-a-real-secret"},
    )

    assert response.status_code == 503
    assert response.json()["error"] == {
        "code": "injected_scan_failure",
        "message": "The tagged set could not be scanned completely.",
        "details": {"run_id": 1, "status": "incomplete", "discovered": 1},
        "request_id": response.headers["X-Request-ID"],
    }
