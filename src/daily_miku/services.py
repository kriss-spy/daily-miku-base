"""Composition root for the v2 application graph."""

from dataclasses import dataclass

from .catalog import SlotCatalog
from .config import Settings
from .content_source import ContentSource, RaindropContentSource
from .correction import SelectionCorrector
from .domain import Calendar, Clock, SystemClock
from .delivery import (
    DeliveryStore,
    EmailDelivery,
    InMemoryDeliveryStore,
    Mailer,
    PostgresDeliveryStore,
    SMTPMailer,
)
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
    delivery_store: DeliveryStore
    mailer: Mailer
    email_delivery: EmailDelivery


def build_services(
    settings: Settings,
    clock: Clock | None = None,
    ledger: OperationalLedger | None = None,
    content_source: ContentSource | None = None,
    image_repository: ImageRepository | None = None,
    blob_store: BlobStore | None = None,
    cover_publisher: CoverPublisher | None = None,
    delivery_store: DeliveryStore | None = None,
    mailer: Mailer | None = None,
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
    images = ImagePipeline(
        catalog,
        resolved_image_repository,
        resolved_blob_store,
        resolved_cover_publisher,
        resolved_clock,
        settings.operator,
    )
    reconciler = Reconciler(
        resolved_ledger, resolved_content_source, calendar, resolved_clock
    )
    resolved_delivery_store = delivery_store or (
        InMemoryDeliveryStore()
        if isinstance(resolved_ledger, InMemoryLedger)
        else PostgresDeliveryStore.from_url(
            settings.database_url.get_secret_value(), local_pool=not settings.serverless
        )
    )
    resolved_mailer = mailer or SMTPMailer(
        settings.smtp_host,
        settings.smtp_port,
        settings.smtp_username,
        settings.smtp_password.get_secret_value(),
    )
    return Services(
        settings=settings,
        clock=resolved_clock,
        calendar=calendar,
        ledger=resolved_ledger,
        content_source=resolved_content_source,
        catalog=catalog,
        reconciler=reconciler,
        corrector=SelectionCorrector(
            resolved_ledger, calendar, resolved_clock, settings.operator
        ),
        initializer=LedgerInitializer(
            resolved_ledger, resolved_content_source, calendar, resolved_clock
        ),
        image_repository=resolved_image_repository,
        blob_store=resolved_blob_store,
        cover_publisher=resolved_cover_publisher,
        images=images,
        delivery_store=resolved_delivery_store,
        mailer=resolved_mailer,
        email_delivery=EmailDelivery(
            reconciler,
            catalog,
            images,
            resolved_blob_store,
            resolved_delivery_store,
            resolved_mailer,
            settings.email_from,
            settings.email_recipients,
        ),
    )
