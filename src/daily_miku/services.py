"""Composition root for the v2 application graph."""

from dataclasses import dataclass
from collections.abc import Callable

from .catalog import SlotCatalog
from .config import Settings
from .content_source import ContentSource, RaindropContentSource
from .domain import Calendar, Clock, SystemClock
from .delivery import (
    DeliveryStore,
    EmailDelivery,
    InMemoryDeliveryStore,
    Mailer,
    PostgresDeliveryStore,
    SMTPMailer,
)
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
from .ledger.migrations import MigrationRunner, expected_schema_version


@dataclass(frozen=True)
class Services:
    """Dependencies shared by HTTP and CLI delivery adapters."""

    settings: Settings
    clock: Clock
    calendar: Calendar
    schema_version: Callable[[], int]
    content_source: ContentSource
    catalog: SlotCatalog
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
    in_memory: bool = False,
    schema_version: Callable[[], int] | None = None,
    ledger: object | None = None,
    content_source: ContentSource | None = None,
    image_repository: ImageRepository | None = None,
    blob_store: BlobStore | None = None,
    cover_publisher: CoverPublisher | None = None,
    delivery_store: DeliveryStore | None = None,
    mailer: Mailer | None = None,
) -> Services:
    """Build the v2 service graph, with optional adapters for isolated tests."""
    # ``ledger`` is accepted only as a test-fixture signal while older tests are
    # migrated; it is never stored, queried, or constructed by this composition.
    in_memory = in_memory or ledger is not None
    resolved_clock = clock or SystemClock()
    calendar = Calendar.named(settings.timezone_name)
    resolved_schema_version = schema_version or (
        (lambda: expected_schema_version())
        if in_memory
        else MigrationRunner.from_url(
            settings.database_url.get_secret_value(),
            local_pool=not settings.serverless,
        ).current_version
    )
    resolved_content_source = content_source or RaindropContentSource(
        settings.raindrop_token.get_secret_value(), "daily-miku"
    )
    if image_repository is not None:
        resolved_image_repository = image_repository
    elif in_memory:
        resolved_image_repository = InMemoryImageRepository()
    else:
        resolved_image_repository = PostgresImageRepository.from_url(
            settings.database_url.get_secret_value(), local_pool=not settings.serverless
        )
    resolved_blob_store = blob_store or (
        InMemoryBlobStore()
        if in_memory
        else VercelBlobStore(settings.blob_read_write_token.get_secret_value())
    )
    resolved_cover_publisher = cover_publisher or (
        InMemoryCoverPublisher()
        if in_memory
        else RaindropCoverPublisher(settings.raindrop_token.get_secret_value())
    )
    catalog = SlotCatalog(
        calendar,
        resolved_clock,
        content_source=resolved_content_source,
        snapshot_ttl_seconds=settings.selection_snapshot_ttl,
    )
    images = ImagePipeline(
        catalog,
        resolved_image_repository,
        resolved_blob_store,
        resolved_cover_publisher,
        resolved_clock,
        settings.operator,
    )
    resolved_delivery_store = delivery_store or (
        InMemoryDeliveryStore()
        if in_memory
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
        schema_version=resolved_schema_version,
        content_source=resolved_content_source,
        catalog=catalog,
        image_repository=resolved_image_repository,
        blob_store=resolved_blob_store,
        cover_publisher=resolved_cover_publisher,
        images=images,
        delivery_store=resolved_delivery_store,
        mailer=resolved_mailer,
        email_delivery=EmailDelivery(
            catalog,
            images,
            resolved_blob_store,
            resolved_delivery_store,
            resolved_mailer,
            settings.email_from,
            settings.email_recipients,
        ),
    )
