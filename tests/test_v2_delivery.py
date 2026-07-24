"""Tests for idempotent image-required email delivery."""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.message import EmailMessage
from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image

from daily_miku.config import Settings
from daily_miku.content_source import InMemoryContentSource, TaggedItem
from daily_miku.delivery import (
    DeliveryBlocked,
    DeliveryDependencyError,
    InMemoryDeliveryStore,
    ReservationKind,
)
from daily_miku.domain import FixedClock
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.main import main
from daily_miku.services import build_services

pytestmark = pytest.mark.unit


@dataclass
class FakeMailer:
    messages: list[EmailMessage] = field(default_factory=list)
    failures_remaining: int = 0

    def send(self, message: EmailMessage) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise DeliveryDependencyError("temporary SMTP failure", transient=True)
        self.messages.append(message)


def delivery_graph(*, recipients: str = "one@example.com,two@example.com"):
    settings = Settings.in_memory().model_copy(
        update={"email_recipients_value": recipients}
    )
    source = InMemoryContentSource(
        (
            TaggedItem(
                7,
                title="Snow Miku",
                excerpt="A winter portrait",
                source_url="https://example.com/art/7",
            ),
        )
    )
    mailer = FakeMailer()
    services = build_services(
        settings,
        clock=FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
        ledger=InMemoryLedger(),
        content_source=source,
        delivery_store=InMemoryDeliveryStore(),
        mailer=mailer,
    )
    services.reconciler.reconcile()
    output = BytesIO()
    Image.new("RGB", (3, 2), (16, 32, 64)).save(output, format="PNG")
    services.images.ingest(7, output.getvalue(), "artist permission")
    return services, mailer


def test_delivery_is_separate_multipart_controlled_and_idempotent() -> None:
    services, mailer = delivery_graph()
    day = date(2026, 7, 19)

    first = services.email_delivery.send(day)
    second = services.email_delivery.send(day)

    assert first.as_dict() == {
        "status": "sent",
        "date": "2026-07-19",
        "recipients": {"configured": 2, "sent": 2, "skipped": 0, "failed": 0},
    }
    assert second.status == "already_sent"
    assert second.skipped == 2
    assert len(mailer.messages) == 2
    assert [message["To"] for message in mailer.messages] == [
        "one@example.com",
        "two@example.com",
    ]
    for message in mailer.messages:
        rendered = message.as_string()
        assert "text/plain" in rendered and "text/html" in rendered
        assert "image/png" in rendered and "Content-ID: <daily-miku>" in rendered
        assert "Snow Miku" in rendered and "2026-07-19" in rendered
        assert "https://example.com/art/7" in rendered


def test_force_creates_new_attempt_and_transient_smtp_is_bounded() -> None:
    services, mailer = delivery_graph(recipients="one@example.com")
    day = date(2026, 7, 19)
    services.email_delivery.send(day)
    forced = services.email_delivery.send(day, force=True)
    mailer.failures_remaining = 3
    failed = services.email_delivery.send(day, force=True)

    assert forced.sent == 1
    assert failed.failed == 1
    assert len(mailer.messages) == 2


def test_reservations_serialize_and_failed_recipient_can_retry() -> None:
    store = InMemoryDeliveryStore()
    day = date(2026, 7, 19)
    first = store.reserve(day, "one@example.com", force=False)
    concurrent = store.reserve(day, "one@example.com", force=False)
    store.fail(first.attempt_id, "smtp_failed")
    retry = store.reserve(day, "one@example.com", force=False)

    assert first.kind is ReservationKind.RESERVED
    assert concurrent.kind is ReservationKind.IN_PROGRESS
    assert retry.kind is ReservationKind.RESERVED


def test_empty_slot_sends_nothing() -> None:
    services, mailer = delivery_graph()

    with pytest.raises(DeliveryBlocked, match="empty"):
        services.email_delivery.send(date(2026, 7, 18))

    assert mailer.messages == []


def test_main_dispatches_dated_forced_json_email() -> None:
    with (
        patch(
            "sys.argv",
            [
                "daily-miku",
                "email",
                "send",
                "--date",
                "2026-07-19",
                "--force",
                "--json",
            ],
        ),
        patch("daily_miku.cli.run_email_send", return_value=0) as run,
        pytest.raises(SystemExit) as exit_info,
    ):
        main()

    assert exit_info.value.code == 0
    run.assert_called_once_with(date(2026, 7, 19), force=True, json_output=True)
