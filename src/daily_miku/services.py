"""Composition root for the v2 application graph."""

from dataclasses import dataclass

from .catalog import SlotCatalog
from .config import Settings
from .content_source import ContentSource, RaindropContentSource
from .correction import SelectionCorrector
from .domain import Calendar, Clock, SystemClock
from .initialize import LedgerInitializer
from .ledger.port import OperationalLedger
from .ledger.postgres import PostgresLedger
from .reconcile import Reconciler


@dataclass(frozen=True)
class Services:
    """Dependencies shared by HTTP and CLI delivery adapters."""

    settings: Settings
    clock: Clock
    calendar: Calendar
    ledger: OperationalLedger
    content_source: ContentSource
    catalog: SlotCatalog
    reconciler: Reconciler
    corrector: SelectionCorrector
    initializer: LedgerInitializer


def build_services(
    settings: Settings,
    clock: Clock | None = None,
    ledger: OperationalLedger | None = None,
    content_source: ContentSource | None = None,
) -> Services:
    """Build the v2 service graph, with optional adapters for isolated tests."""
    resolved_clock = clock or SystemClock()
    calendar = Calendar.named(settings.timezone_name)
    resolved_ledger = ledger or PostgresLedger.from_url(
        settings.database_url.get_secret_value(), local_pool=not settings.serverless
    )
    resolved_content_source = content_source or RaindropContentSource(
        settings.raindrop_token.get_secret_value(), settings.tag
    )
    return Services(
        settings=settings,
        clock=resolved_clock,
        calendar=calendar,
        ledger=resolved_ledger,
        content_source=resolved_content_source,
        catalog=SlotCatalog(resolved_ledger, calendar, resolved_clock),
        reconciler=Reconciler(
            resolved_ledger, resolved_content_source, calendar, resolved_clock
        ),
        corrector=SelectionCorrector(
            resolved_ledger, calendar, resolved_clock, settings.operator
        ),
        initializer=LedgerInitializer(
            resolved_ledger, resolved_content_source, calendar, resolved_clock
        ),
    )
