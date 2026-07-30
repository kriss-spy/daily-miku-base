"""Tests for safe deployment diagnostics."""

from dataclasses import dataclass

import pytest

from daily_miku.config import Settings
from daily_miku.content_source import InMemoryContentSource
from daily_miku.doctor import Doctor, build_doctor
from daily_miku.images.blob import InMemoryBlobStore

pytestmark = pytest.mark.unit


@dataclass
class FakeMigrations:
    current: int = 4
    expected_version: int = 4

    def current_version(self) -> int:
        return self.current


class FakeSMTP:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.started_tls = False
        self.authenticated = False
        self.sent = False

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        assert username and password
        self.authenticated = True


def test_doctor_checks_dependencies_and_cleans_blob_without_email() -> None:
    blob = InMemoryBlobStore()
    smtp = FakeSMTP()
    doctor = build_doctor(
        Settings.in_memory(),
        FakeMigrations(),  # type: ignore[arg-type]
        InMemoryContentSource(),
        blob,
        smtp_factory=lambda *args, **kwargs: smtp,  # type: ignore[arg-type]
    )

    report = doctor.run()

    assert report.status == "ok"
    assert [check.name for check in report.checks] == [
        "configuration",
        "database",
        "raindrop",
        "blob",
        "smtp",
    ]
    assert blob.objects == {}
    assert smtp.started_tls and smtp.authenticated and not smtp.sent


def test_doctor_continues_independent_checks_and_hides_exceptions() -> None:
    called: list[str] = []

    def failed() -> None:
        raise RuntimeError("secret-token-must-not-appear")

    def successful() -> None:
        called.append("ok")

    report = Doctor(failed, successful, failed, successful).run()

    assert [check.status for check in report.checks] == [
        "ok",
        "failed",
        "ok",
        "failed",
        "ok",
    ]
    assert called == ["ok", "ok"]
    assert "secret-token" not in str(report.as_dict())


def test_failed_blob_verification_still_cleans_temporary_object() -> None:
    class MismatchBlob(InMemoryBlobStore):
        def get(self, key: str) -> tuple[bytes, str]:
            super().get(key)
            return b"wrong", "image/png"

    blob = MismatchBlob()
    report = build_doctor(
        Settings.in_memory(),
        FakeMigrations(),  # type: ignore[arg-type]
        InMemoryContentSource(),
        blob,
        smtp_factory=FakeSMTP,  # type: ignore[arg-type]
    ).run()

    assert (
        next(check for check in report.checks if check.name == "blob").status
        == "failed"
    )
    assert blob.objects == {}
