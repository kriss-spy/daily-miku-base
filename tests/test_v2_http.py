"""Tests for the injectable v2 FastAPI shell."""

import json

import pytest
from fastapi.testclient import TestClient

from daily_miku.config import Settings
from daily_miku.http import create_app
from daily_miku.logging_config import JSONFormatter
from daily_miku.services import build_services

pytestmark = pytest.mark.unit


def test_composition_root_builds_an_in_memory_http_graph() -> None:
    settings = Settings.in_memory()
    services = build_services(settings)
    app = create_app(settings, services)

    assert app.state.services is services
    assert app.state.services.calendar.timezone.key == "Asia/Shanghai"


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
