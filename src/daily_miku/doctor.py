"""Read-only deployment diagnostics."""

import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256

from .config import Settings
from .content_source import ContentSource, ScanStatus
from .images.blob import BlobStore
from .ledger.migrations import MigrationRunner


@dataclass(frozen=True)
class DoctorCheck:
    """One safe diagnostic result."""

    name: str
    status: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "message": self.message}


@dataclass(frozen=True)
class DoctorReport:
    """Complete ordered deployment diagnosis."""

    checks: tuple[DoctorCheck, ...]

    @property
    def status(self) -> str:
        return "ok" if all(check.status == "ok" for check in self.checks) else "failed"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": [check.as_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class Doctor:
    """Run every independent check and safely report all outcomes."""

    database: Callable[[], None]
    raindrop: Callable[[], None]
    blob: Callable[[], None]
    smtp: Callable[[], None]

    def run(self) -> DoctorReport:
        checks = [DoctorCheck("configuration", "ok", "Configuration is valid.")]
        for name, operation in (
            ("database", self.database),
            ("raindrop", self.raindrop),
            ("blob", self.blob),
            ("smtp", self.smtp),
        ):
            try:
                operation()
                checks.append(DoctorCheck(name, "ok", f"{name.title()} check passed."))
            except Exception:
                checks.append(
                    DoctorCheck(name, "failed", f"{name.title()} check failed safely.")
                )
        return DoctorReport(tuple(checks))


def build_doctor(
    settings: Settings,
    migrations: MigrationRunner,
    content_source: ContentSource,
    blob_store: BlobStore,
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
) -> Doctor:
    """Build non-mutating production diagnostics from validated settings."""

    def database() -> None:
        if migrations.current_version() != migrations.expected_version:
            raise RuntimeError("Schema version does not match the release")

    def raindrop() -> None:
        if content_source.scan_tagged().status is not ScanStatus.COMPLETE:
            raise RuntimeError("Raindrop tag query was incomplete")

    def blob() -> None:
        data = b"daily-miku-doctor"
        digest = sha256(data).hexdigest()
        key = f"images/{digest}.png"
        try:
            blob_store.put(key, data, "image/png")
            actual, content_type = blob_store.get(key)
            if actual != data or content_type != "image/png":
                raise RuntimeError("Blob verification mismatch")
        finally:
            blob_store.delete(key)

    def smtp() -> None:
        with smtp_factory(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(
                settings.smtp_username, settings.smtp_password.get_secret_value()
            )

    return Doctor(database, raindrop, blob, smtp)
