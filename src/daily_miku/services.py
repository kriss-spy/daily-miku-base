"""Composition root and in-memory seams for the v2 application graph."""

from dataclasses import dataclass, field

from .catalog import SlotCatalog
from .config import Settings
from .domain import Calendar, Clock, SystemClock
from .ledger.port import Ledger
from .ledger.postgres import PostgresLedger


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
    ledger: Ledger
    content_source: InMemoryContentSource
    catalog: SlotCatalog


def build_services(
    settings: Settings,
    clock: Clock | None = None,
    ledger: Ledger | None = None,
) -> Services:
    """Build the v2 service graph, with optional adapters for isolated tests."""
    resolved_clock = clock or SystemClock()
    calendar = Calendar.named(settings.timezone_name)
    resolved_ledger = ledger or PostgresLedger.from_url(
        settings.database_url.get_secret_value(), local_pool=not settings.serverless
    )
    return Services(
        settings=settings,
        clock=resolved_clock,
        calendar=calendar,
        ledger=resolved_ledger,
        content_source=InMemoryContentSource(),
        catalog=SlotCatalog(resolved_ledger, calendar, resolved_clock),
    )
