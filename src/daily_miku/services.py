"""Composition root for the v2 application graph."""

from dataclasses import dataclass

from .catalog import SlotCatalog
from .config import Settings
from .content_source import ContentSource, RaindropContentSource
from .correction import SelectionCorrector
from .domain import Calendar, Clock, SystemClock
from .initialize import LedgerInitializer
from .images.blob import BlobStore, InMemoryBlobStore, VercelBlobStore
from .images.pipeline import ImagePipeline
from .images.publisher import (
    CoverPublisher,
    InMemoryCoverPublisher,
    RaindropCoverPublisher,
)
from .images.store import (
    ImageRepository,
    InMemoryImageRepository,
    PostgresImageRepository,
)
from .ledger.memory import InMemoryLedger
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
    image_repository: ImageRepository
    blob_store: BlobStore
    cover_publisher: CoverPublisher
    images: ImagePipeline


def build_services(
    settings: Settings,
    clock: Clock | None = None,
    ledger: OperationalLedger | None = None,
    content_source: ContentSource | None = None,
    image_repository: ImageRepository | None = None,
    blob_store: BlobStore | None = None,
    cover_publisher: CoverPublisher | None = None,
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
    if image_repository is not None:
        resolved_image_repository = image_repository
    elif isinstance(resolved_ledger, InMemoryLedger):
        resolved_image_repository = InMemoryImageRepository()
    else:
        resolved_image_repository = PostgresImageRepository.from_url(
            settings.database_url.get_secret_value(), local_pool=not settings.serverless
        )
    resolved_blob_store = blob_store or (
        InMemoryBlobStore()
        if isinstance(resolved_ledger, InMemoryLedger)
        else VercelBlobStore(settings.blob_read_write_token.get_secret_value())
    )
    resolved_cover_publisher = cover_publisher or (
        InMemoryCoverPublisher()
        if isinstance(resolved_ledger, InMemoryLedger)
        else RaindropCoverPublisher(settings.raindrop_token.get_secret_value())
    )
    catalog = SlotCatalog(
        resolved_ledger,
        calendar,
        resolved_clock,
        content_source=resolved_content_source,
    )
    return Services(
        settings=settings,
        clock=resolved_clock,
        calendar=calendar,
        ledger=resolved_ledger,
        content_source=resolved_content_source,
        catalog=catalog,
        reconciler=Reconciler(
            resolved_ledger, resolved_content_source, calendar, resolved_clock
        ),
        corrector=SelectionCorrector(
            resolved_ledger, calendar, resolved_clock, settings.operator
        ),
        initializer=LedgerInitializer(
            resolved_ledger, resolved_content_source, calendar, resolved_clock
        ),
        image_repository=resolved_image_repository,
        blob_store=resolved_blob_store,
        cover_publisher=resolved_cover_publisher,
        images=ImagePipeline(
            catalog,
            resolved_image_repository,
            resolved_blob_store,
            resolved_cover_publisher,
            resolved_clock,
            settings.operator,
        ),
    )
