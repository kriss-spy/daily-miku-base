"""Composition root and in-memory seams for the v2 application graph."""

from dataclasses import dataclass, field

from .config import Settings
from .domain import Calendar, Clock, SlotCandidate, SystemClock


@dataclass
class InMemoryLedger:
    """In-memory candidate store used by isolated application slices."""

    candidates: dict[str, list[SlotCandidate]] = field(default_factory=dict)


@dataclass
class InMemoryContentSource:
    """In-memory Raindrop-authoritative content seam."""

    items: dict[int, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class Services:
    """Dependencies shared by HTTP and CLI delivery adapters."""

    settings: Settings
    clock: Clock
    calendar: Calendar
    ledger: InMemoryLedger
    content_source: InMemoryContentSource


def build_services(settings: Settings, clock: Clock | None = None) -> Services:
    """Build the runnable in-memory v2 service graph."""
    return Services(
        settings=settings,
        clock=clock or SystemClock(),
        calendar=Calendar.named(settings.timezone_name),
        ledger=InMemoryLedger(),
        content_source=InMemoryContentSource(),
    )
