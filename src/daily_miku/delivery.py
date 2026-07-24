"""Idempotent per-recipient Daily Miku email delivery."""

import html
import smtplib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.message import EmailMessage
from enum import StrEnum
from threading import Lock
from typing import Protocol, cast

import psycopg
from psycopg_pool import PoolTimeout

from .catalog import SlotCatalog
from .domain import SlotState
from .images import ImageResolutionKind
from .images.blob import BlobDependencyError, BlobStore
from .images.pipeline import ImagePipeline
from .ledger.database import ConnectionFactory, postgres_connections
from .reconcile import Reconciler


class DeliveryDependencyError(RuntimeError):
    """A delivery dependency failed after any safe retries."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class DeliveryBlocked(ValueError):
    """A valid Slot or image state prevents email delivery."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


class ReservationKind(StrEnum):
    RESERVED = "reserved"
    ALREADY_SENT = "already_sent"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class Reservation:
    """One durable delivery attempt reservation."""

    attempt_id: int
    kind: ReservationKind


class DeliveryStore(Protocol):
    """Durable per-date and per-recipient delivery outcomes."""

    def reserve(self, day: date, recipient: str, *, force: bool) -> Reservation: ...

    def succeed(self, attempt_id: int) -> None: ...

    def fail(self, attempt_id: int, reason: str) -> None: ...


@dataclass
class InMemoryDeliveryStore:
    """Thread-safe delivery store fake."""

    attempts: dict[int, tuple[date, str, str]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def reserve(self, day: date, recipient: str, *, force: bool) -> Reservation:
        with self._lock:
            matching = [
                (attempt_id, status)
                for attempt_id, (attempt_day, address, status) in self.attempts.items()
                if attempt_day == day and address == recipient
            ]
            if any(status == "pending" for _, status in matching):
                return Reservation(0, ReservationKind.IN_PROGRESS)
            if not force and any(status == "sent" for _, status in matching):
                return Reservation(0, ReservationKind.ALREADY_SENT)
            attempt_id = len(self.attempts) + 1
            self.attempts[attempt_id] = (day, recipient, "pending")
            return Reservation(attempt_id, ReservationKind.RESERVED)

    def succeed(self, attempt_id: int) -> None:
        with self._lock:
            day, recipient, _ = self.attempts[attempt_id]
            self.attempts[attempt_id] = (day, recipient, "sent")

    def fail(self, attempt_id: int, reason: str) -> None:
        del reason
        with self._lock:
            day, recipient, _ = self.attempts[attempt_id]
            self.attempts[attempt_id] = (day, recipient, "failed")


@dataclass(frozen=True)
class PostgresDeliveryStore:
    """Transactional Postgres reservations and outcomes."""

    connection_factory: ConnectionFactory

    @classmethod
    def from_url(
        cls, database_url: str, *, local_pool: bool = False
    ) -> "PostgresDeliveryStore":
        return cls(postgres_connections(database_url, local_pool=local_pool))

    def reserve(self, day: date, recipient: str, *, force: bool) -> Reservation:
        try:
            with self.connection_factory() as connection:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{day.isoformat()}:{recipient}",),
                )
                if not force:
                    sent = connection.execute(
                        "SELECT attempt_id FROM email_delivery_attempts "
                        "WHERE selection_day = %s AND recipient = %s "
                        "AND status = 'sent' LIMIT 1",
                        (day, recipient),
                    ).fetchone()
                    if sent is not None:
                        return Reservation(0, ReservationKind.ALREADY_SENT)
                pending = connection.execute(
                    "SELECT attempt_id FROM email_delivery_attempts "
                    "WHERE selection_day = %s AND recipient = %s "
                    "AND status = 'pending' LIMIT 1",
                    (day, recipient),
                ).fetchone()
                if pending is not None:
                    return Reservation(0, ReservationKind.IN_PROGRESS)
                row = connection.execute(
                    "INSERT INTO email_delivery_attempts "
                    "(selection_day, recipient, forced, status) "
                    "VALUES (%s, %s, %s, 'pending') RETURNING attempt_id",
                    (day, recipient, force),
                ).fetchone()
        except (psycopg.Error, PoolTimeout) as exc:
            raise DeliveryDependencyError("Delivery reservation failed") from exc
        if row is None:
            raise DeliveryDependencyError("Delivery reservation failed")
        return Reservation(int(row[0]), ReservationKind.RESERVED)

    def succeed(self, attempt_id: int) -> None:
        self._finish(attempt_id, "sent", None)

    def fail(self, attempt_id: int, reason: str) -> None:
        self._finish(attempt_id, "failed", reason)

    def _finish(self, attempt_id: int, status: str, reason: str | None) -> None:
        try:
            with self.connection_factory() as connection:
                row = connection.execute(
                    "UPDATE email_delivery_attempts SET status = %s, "
                    "finished_at = %s, failure_code = %s "
                    "WHERE attempt_id = %s AND status = 'pending' RETURNING attempt_id",
                    (status, datetime.now(timezone.utc), reason, attempt_id),
                ).fetchone()
        except (psycopg.Error, PoolTimeout) as exc:
            raise DeliveryDependencyError("Delivery outcome recording failed") from exc
        if row is None:
            raise DeliveryDependencyError("Delivery reservation is not pending")


class Mailer(Protocol):
    """Send one already-composed message to one recipient."""

    def send(self, message: EmailMessage) -> None: ...


@dataclass(frozen=True)
class SMTPMailer:
    """Authenticated STARTTLS SMTP adapter."""

    host: str
    port: int
    username: str
    password: str

    def send(self, message: EmailMessage) -> None:
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            transient = isinstance(exc, OSError) or (
                isinstance(exc, smtplib.SMTPResponseException) and exc.smtp_code >= 500
            )
            raise DeliveryDependencyError(
                "SMTP delivery failed", transient=transient
            ) from exc


@dataclass(frozen=True)
class DeliveryReport:
    """Address-free batch delivery result."""

    status: str
    day: date
    configured: int
    sent: int
    skipped: int
    failed: int

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "date": self.day.isoformat(),
            "recipients": {
                "configured": self.configured,
                "sent": self.sent,
                "skipped": self.skipped,
                "failed": self.failed,
            },
        }


@dataclass(frozen=True)
class EmailDelivery:
    """Shared reconciliation, Slot, image, and recipient delivery behavior."""

    reconciler: Reconciler
    catalog: SlotCatalog
    images: ImagePipeline
    blobs: BlobStore
    store: DeliveryStore
    mailer: Mailer
    sender: str
    recipients: tuple[str, ...]

    def send(self, day: date, *, force: bool = False) -> DeliveryReport:
        report = self.reconciler.reconcile()
        if report.status.value != "complete":
            raise DeliveryDependencyError("Reconciliation did not complete")
        slot = self.catalog.get_slot(day)
        if slot.state is SlotState.EMPTY:
            raise DeliveryBlocked("empty", "The Daily Slot is empty.")
        if slot.state is SlotState.CONFLICT:
            raise DeliveryBlocked("conflict", "The Daily Slot has a conflict.")
        resolution = self.images.resolve_image(day)
        if resolution.kind is ImageResolutionKind.NO_IMAGE:
            raise DeliveryBlocked("failed", "No controlled image is available.")
        if resolution.kind is not ImageResolutionKind.REDIRECT:
            raise DeliveryDependencyError("The controlled image is unavailable")
        provenance = self.images.repository.active_for(slot.items[0].raindrop_id)
        if provenance is None:
            raise DeliveryBlocked("failed", "No controlled image is available.")
        try:
            image_bytes, content_type = self.blobs.get(provenance.blob_key)
        except BlobDependencyError as exc:
            raise DeliveryDependencyError(
                "The controlled image is unavailable"
            ) from exc

        sent = skipped = failed = 0
        for recipient in self.recipients:
            reservation = self.store.reserve(day, recipient, force=force)
            if reservation.kind is not ReservationKind.RESERVED:
                skipped += 1
                continue
            message = _message(
                self.sender, recipient, slot.items[0], day, image_bytes, content_type
            )
            try:
                for attempt in range(3):
                    try:
                        self.mailer.send(message)
                        break
                    except DeliveryDependencyError as exc:
                        if not exc.transient or attempt == 2:
                            raise
            except DeliveryDependencyError:
                self.store.fail(reservation.attempt_id, "smtp_failed")
                failed += 1
                continue
            # If SMTP accepted the message but this commit fails, preserve the
            # pending reservation: retrying could duplicate an accepted message.
            self.store.succeed(reservation.attempt_id)
            sent += 1
        status = "failed" if failed else ("already_sent" if not sent else "sent")
        return DeliveryReport(status, day, len(self.recipients), sent, skipped, failed)


def _message(
    sender: str,
    recipient: str,
    item: object,
    day: date,
    data: bytes,
    content_type: str,
) -> EmailMessage:
    title = str(getattr(item, "title"))
    excerpt = getattr(item, "excerpt")
    source = getattr(item, "source_url")
    plain = f"Daily Miku for {day.isoformat()}\n\n{title}"
    if excerpt:
        plain += f"\n\n{excerpt}"
    if source:
        plain += f"\n\nSource: {source}"
    body = f"<h1>{html.escape(title)}</h1><p>Selection Day: {day.isoformat()}</p>"
    if excerpt:
        body += f"<p>{html.escape(str(excerpt))}</p>"
    if source:
        safe_source = html.escape(str(source), quote=True)
        body += f'<p><a href="{safe_source}">Source</a></p>'
    body += '<img src="cid:daily-miku" alt="Daily Miku artwork">'
    message = EmailMessage()
    message["Subject"] = f"Daily Miku - {day.isoformat()}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(plain)
    message.add_alternative(body, subtype="html")
    subtype = content_type.split("/", 1)[1]
    payload = cast(list[EmailMessage], message.get_payload())
    payload[1].add_related(data, maintype="image", subtype=subtype, cid="<daily-miku>")
    return message
