"""CLI commands for daily-miku-base."""

import json
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import email as email_module
from .catalog import CatalogSlot, InvalidCursor, SlotCatalog, slot_document
from .config import (
    ConfigurationError,
    ImageSettings,
    InitializationSettings,
    Settings,
)
from .content_source import ContentDependencyError, RaindropContentSource
from .domain import Calendar, FutureSelectionDay, SystemClock
from .delivery import DeliveryBlocked, DeliveryDependencyError
from .doctor import build_doctor
from .images import ImageBlocked, ImageDependencyError, ImagePipeline
from .images.blob import BlobStore, InMemoryBlobStore, VercelBlobStore
from .images.publisher import RaindropCoverPublisher
from .images.store import PostgresImageRepository
from .ledger.database import postgres_connections
from .ledger.migrations import MigrationRunner
from .raindrop import RaindropSelectionTagStore, get_client
from .selection_initialize import (
    SelectionInitializationDependencyError,
    SelectionTagInitializer,
)
from .selections import MultiDateAssignment
from .services import build_services

logger = logging.getLogger("daily_miku.v2.cli")


def _error_document(code: str, message: str) -> dict[str, object]:
    return {
        "status": "failed",
        "error": {"code": code, "message": message, "details": {}},
    }


def run_email_send(
    requested_date: date | None,
    *,
    force: bool = False,
    json_output: bool = False,
) -> int:
    """Deliver one image-required Daily Slot from current selection tags."""
    try:
        settings = Settings.from_environment()
        services = build_services(settings)
        day = requested_date or services.calendar.today(services.clock).value
        report = services.email_delivery.send(day, force=force)
    except ConfigurationError as exc:
        document = _error_document("configuration_invalid", str(exc))
        if json_output:
            print(json.dumps(document))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    except (FutureSelectionDay, DeliveryBlocked) as exc:
        status = exc.status if isinstance(exc, DeliveryBlocked) else "failed"
        document = _error_document(status, str(exc))
        if json_output:
            print(json.dumps(document))
        else:
            print(str(exc), file=sys.stderr)
        return 5
    except (
        DeliveryDependencyError,
        ContentDependencyError,
    ):
        message = "Email delivery could not access a required dependency."
        if json_output:
            print(json.dumps(_error_document("delivery_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    if json_output:
        print(json.dumps(report.as_dict()))
    else:
        counts = report.as_dict()["recipients"]
        print(f"Email delivery {report.status} for {report.day.isoformat()}: {counts}")
    return 4 if report.failed else 0


def run_doctor(*, json_output: bool = False) -> int:
    """Diagnose configuration and all independent deployment dependencies."""
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        document = {
            "status": "failed",
            "checks": [
                {"name": "configuration", "status": "failed", "message": str(exc)},
                *[
                    {
                        "name": name,
                        "status": "skipped",
                        "message": "Valid configuration is required.",
                    }
                    for name in ("database", "raindrop", "blob", "smtp")
                ],
            ],
        }
        print(json.dumps(document) if json_output else f"configuration: failed - {exc}")
        return 3
    services = build_services(settings)
    migrations = MigrationRunner(
        postgres_connections(
            settings.database_url.get_secret_value(), local_pool=not settings.serverless
        )
    )
    report = build_doctor(
        settings, migrations, services.content_source, services.blob_store
    ).run()
    if json_output:
        print(json.dumps(report.as_dict()))
    else:
        for check in report.checks:
            print(f"{check.name}: {check.status} - {check.message}")
    return 0 if report.status == "ok" else 4


def run_archive_list(
    *, cursor: str | None = None, limit: int = 24, json_output: bool = False
) -> int:
    """Render the shared newest-first non-empty Slot archive."""
    try:
        settings = Settings.from_environment()
        services = build_services(settings)
        page = services.catalog.archive(cursor=cursor, limit=limit)
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    except (ValueError, InvalidCursor) as exc:
        if json_output:
            print(json.dumps(_error_document("archive_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except ContentDependencyError:
        message = "Archive dependencies are temporarily unavailable."
        if json_output:
            print(json.dumps(_error_document("archive_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    today = services.calendar.today(services.clock)
    document = {
        "items": [slot_document(slot, today) for slot in page.items],
        "next_cursor": page.next_cursor,
        "links": {
            "self": f"/api/archive?limit={limit}"
            + (f"&cursor={cursor}" if cursor else ""),
            "next": (
                f"/api/archive?limit={limit}&cursor={page.next_cursor}"
                if page.next_cursor
                else None
            ),
        },
    }
    if json_output:
        print(json.dumps(document))
    elif not page.items:
        print("The Daily Slot archive is empty.")
    else:
        for slot in page.items:
            print(f"{slot.day.value.isoformat()}  {slot.state.value}")
            for item in slot.items:
                print(f"  {item.title} (Raindrop ID {item.raindrop_id})")
    return 0


def read_slot(
    catalog: SlotCatalog, requested_date: date | None, *, json_output: bool = False
) -> int:
    """Read and render one Slot through the shared catalog contract."""
    try:
        slot = (
            catalog.today()
            if requested_date is None
            else catalog.get_slot(requested_date)
        )
        document = slot_document(slot, catalog.calendar.today(catalog.clock))
        if json_output:
            print(json.dumps(document))
        else:
            _print_human_slot(slot)
    except FutureSelectionDay as exc:
        if json_output:
            print(json.dumps(_error_document("future_selection_day", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 5
    except MultiDateAssignment as exc:
        if json_output:
            print(json.dumps(_error_document("multi_date_assignment", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 5
    except ContentDependencyError:
        message = "Current Daily Slot data is temporarily unavailable."
        if json_output:
            print(json.dumps(_error_document("slot_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    except Exception:
        logger.exception("unexpected_slot_read_failure")
        message = "An unexpected Daily Slot read failure occurred."
        if json_output:
            print(json.dumps(_error_document("internal_error", message)))
        else:
            print(message, file=sys.stderr)
        return 1

    return 0


def _print_human_slot(slot: CatalogSlot) -> None:
    """Render complete state-aware operator output."""
    print(f"Daily Slot {slot.day.value.isoformat()}: {slot.state.value}")
    if not slot.items:
        print("The Daily Slot is empty.")
        return
    for item in slot.items:
        print(f"  {item.title}")
        print(f"    Source: {item.source_url or '(unavailable)'}")
        print(f"    Raindrop ID: {item.raindrop_id}")


def run_slot_read(date_value: str | None, *, json_output: bool = False) -> int:
    """Validate a Slot invocation, compose dependencies, and execute it."""
    requested_date: date | None = None
    if date_value is not None:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
                raise ValueError
            requested_date = date.fromisoformat(date_value)
        except ValueError:
            message = "DATE must be a valid YYYY-MM-DD calendar date."
            if json_output:
                print(json.dumps(_error_document("invocation_invalid", message)))
            else:
                print(message, file=sys.stderr)
            return 2
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    try:
        catalog = build_services(settings).catalog
    except ContentDependencyError:
        message = "Current Daily Slot data is temporarily unavailable."
        if json_output:
            print(json.dumps(_error_document("slot_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    except Exception:
        logger.exception("unexpected_slot_service_construction_failure")
        message = "An unexpected Daily Slot read failure occurred."
        if json_output:
            print(json.dumps(_error_document("internal_error", message)))
        else:
            print(message, file=sys.stderr)
        return 1
    return read_slot(catalog, requested_date, json_output=json_output)


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def initialize_selection_tags(
    initializer: SelectionTagInitializer,
    *,
    apply: bool = False,
    json_output: bool = False,
) -> int:
    """Run Raindrop dated-tag initialization and render per-item outcomes."""
    try:
        report = initializer.initialize(apply=apply)
    except SelectionInitializationDependencyError:
        message = "Selection initialization could not access a complete safe snapshot."
        if json_output:
            print(
                json.dumps(_error_document("initialization_dependency_failed", message))
            )
        else:
            print(message, file=sys.stderr)
        return 4
    except Exception:
        logger.exception("unexpected_selection_initialization_failure")
        message = "An unexpected selection initialization failure occurred."
        if json_output:
            print(json.dumps(_error_document("internal_error", message)))
        else:
            print(message, file=sys.stderr)
        return 1

    if json_output:
        document = report.as_dict()
        if report.status == "incomplete":
            document["error"] = {
                "code": "initialization_dependency_failed",
                "message": "Selection initialization stopped after a dependency failure.",
                "details": {},
            }
        elif report.status == "blocked":
            document["error"] = {
                "code": "initialization_drift_blocked",
                "message": "Selection initialization was blocked by concurrent changes.",
                "details": {},
            }
        print(json.dumps(document))
    else:
        action = "Apply" if apply else "Dry run"
        print(
            f"{action}: discovered {report.discovered_count}, "
            f"proposed {len(report.proposals)}, applied {report.applied_count}; "
            f"status {report.status}."
        )
        for proposal in report.proposals:
            print(
                f"  Raindrop {proposal.raindrop_id}: "
                f"lastUpdate {_utc_timestamp(proposal.last_update)}, "
                f"Selection Day {proposal.selection_day}, "
                f"tags {list(proposal.current_tags)} -> {proposal.proposed_tag}"
            )
        for result in report.results:
            print(f"  Result {result.raindrop_id}: {result.status}")
        for name, diagnostics in (
            ("Malformed dated tag", report.malformed_dated_tags),
            ("Multi-date assignment", report.multi_date_assignments),
            ("Duplicate identity", report.duplicate_identities),
            ("Same-date conflict", report.same_date_conflicts),
        ):
            for diagnostic in diagnostics:
                print(
                    f"  {name} {diagnostic.identity}: "
                    + ", ".join(str(value) for value in diagnostic.raindrop_ids)
                )
    if report.status == "incomplete":
        return 4
    if report.status == "blocked":
        return 5
    return 0


def run_selection_initialize(*, apply: bool = False, json_output: bool = False) -> int:
    """Build only Raindrop dependencies and initialize canonical dated tags."""
    try:
        settings = InitializationSettings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    initializer = SelectionTagInitializer(
        RaindropSelectionTagStore(settings.raindrop_token.get_secret_value()),
        settings.timezone_name,
    )
    return initialize_selection_tags(initializer, apply=apply, json_output=json_output)


def ingest_image(
    pipeline: ImagePipeline,
    raindrop_id: int,
    data: bytes,
    authorization_note: str,
    *,
    json_output: bool = False,
) -> int:
    """Ingest authorized bytes and render only safe provenance facts."""
    try:
        record = pipeline.ingest(raindrop_id, data, authorization_note)
    except (ValueError, ImageBlocked) as exc:
        code = (
            "image_rejected" if isinstance(exc, ImageBlocked) else "invocation_invalid"
        )
        exit_code = 5 if isinstance(exc, ImageBlocked) else 2
        if json_output:
            print(json.dumps(_error_document(code, str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return exit_code
    except ImageDependencyError:
        message = "Image ingestion could not access a required dependency."
        if json_output:
            print(json.dumps(_error_document("image_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    document = {
        "status": "ingested",
        "raindrop_id": record.raindrop_id,
        "digest": record.digest,
        "blob_key": record.blob_key,
        "content_type": record.content_type,
        "width": record.width,
        "height": record.height,
    }
    if json_output:
        print(json.dumps(document))
    else:
        print(
            f"Ingested controlled image for Raindrop {record.raindrop_id} "
            f"as {record.blob_key}."
        )
    return 0


def withdraw_image(
    pipeline: ImagePipeline,
    raindrop_id: int,
    reason: str,
    *,
    json_output: bool = False,
) -> int:
    """Record a durable withdrawal tombstone and render safe facts."""
    try:
        record = pipeline.withdraw(raindrop_id, reason)
    except ValueError as exc:
        if json_output:
            print(json.dumps(_error_document("invocation_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except ImageDependencyError:
        message = "Image withdrawal could not access durable storage."
        if json_output:
            print(json.dumps(_error_document("image_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    document = {
        "status": "withdrawn",
        "raindrop_id": record.raindrop_id,
        "reason": record.reason,
        "operator": record.operator,
        "withdrawn_at": _utc_timestamp(record.withdrawn_at),
    }
    if json_output:
        print(json.dumps(document))
    else:
        print(f"Withdrew controlled image for Raindrop {record.raindrop_id}.")
    return 0


def _configured_image_pipeline(settings: ImageSettings) -> ImagePipeline:
    """Compose only the dependencies required by image operator commands."""
    clock = SystemClock()
    calendar = Calendar.named(settings.timezone_name)
    source = RaindropContentSource(
        settings.raindrop_token.get_secret_value(), "daily-miku"
    )
    blob_store: BlobStore = (
        InMemoryBlobStore()
        if settings.blob_read_write_token is None
        else VercelBlobStore(settings.blob_read_write_token.get_secret_value())
    )
    return ImagePipeline(
        SlotCatalog(calendar, clock, source),
        PostgresImageRepository.from_url(
            settings.database_url.get_secret_value(), local_pool=not settings.serverless
        ),
        blob_store,
        RaindropCoverPublisher(settings.raindrop_token.get_secret_value()),
        clock,
        settings.operator,
    )


def run_image_ingest(
    raindrop_id_value: str,
    file_value: str,
    authorization_note: str,
    *,
    json_output: bool = False,
) -> int:
    """Validate invocation/configuration and ingest one local raster file."""
    try:
        raindrop_id = int(raindrop_id_value)
        if raindrop_id <= 0 or not authorization_note.strip():
            raise ValueError
        data = Path(file_value).read_bytes()
    except (ValueError, OSError):
        message = (
            "RAINDROP_ID must be positive, FILE must be readable, and "
            "--authorization-note must not be blank."
        )
        if json_output:
            print(json.dumps(_error_document("invocation_invalid", message)))
        else:
            print(message, file=sys.stderr)
        return 2
    try:
        settings = ImageSettings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    return ingest_image(
        _configured_image_pipeline(settings),
        raindrop_id,
        data,
        authorization_note,
        json_output=json_output,
    )


def run_image_withdraw(
    raindrop_id_value: str, reason: str, *, json_output: bool = False
) -> int:
    """Validate invocation/configuration and withdraw one controlled image."""
    try:
        raindrop_id = int(raindrop_id_value)
        if raindrop_id <= 0 or not reason.strip():
            raise ValueError
    except ValueError:
        message = "RAINDROP_ID must be positive and --reason must not be blank."
        if json_output:
            print(json.dumps(_error_document("invocation_invalid", message)))
        else:
            print(message, file=sys.stderr)
        return 2
    try:
        settings = ImageSettings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    return withdraw_image(
        _configured_image_pipeline(settings),
        raindrop_id,
        reason,
        json_output=json_output,
    )


def fetch_today():
    """Fetch and display today's daily miku."""
    client = get_client()
    item = client.get_today()

    if item:
        formatted = client.format_response(item)
        print(json.dumps(formatted, indent=2))
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"No daily miku found for {today}", file=sys.stderr)
        sys.exit(1)


def fetch_date(date: str):
    """Fetch and display daily miku for a specific date."""
    client = get_client()
    item = client.get_by_date(date)

    if item:
        formatted = client.format_response(item, date)
        print(json.dumps(formatted, indent=2))
    else:
        print(f"No daily miku found for {date}", file=sys.stderr)
        sys.exit(1)


def test_connection():
    """Test Raindrop.io API connection."""
    print("Testing connection to Raindrop.io...")
    client = get_client()

    if client.test_connection():
        print("✓ Connection successful!")
        print(f"  Token: {client.token[:10]}...")  # type: ignore[index]
        print(f"  Tag: #{client.tag}")

        # Fetch a sample to verify tag works
        items = client.fetch_raindrops(perpage=1)
        if items:
            print(f"✓ Found bookmarks with #{client.tag} tag")
            print(f"  Latest: {items[0].get('title', 'Untitled')}")
        else:
            print(f"⚠ No bookmarks found with #{client.tag} tag")
    else:
        print("✗ Connection failed!", file=sys.stderr)
        sys.exit(1)


def list_recent(limit: int = 10):
    """List recent daily miku bookmarks."""
    client = get_client()
    items = client.fetch_raindrops(perpage=limit)

    if not items:
        print("No bookmarks found", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(items)} recent bookmarks:\n")
    for item in items:
        created = item.get("created", "")
        if created:
            date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
                "%Y-%m-%d"
            )
        else:
            date = "Unknown"

        title = item.get("title", "Untitled")
        link = item.get("link", "")
        print(f"  {date}: {title}")
        print(f"    Source: {link}")
        print()


def send_email():
    """Send today's daily miku via email with failure tracking."""
    from datetime import timezone, timedelta

    # Use UTC+8 timezone (Asia)
    LOCAL_TZ = timezone(timedelta(hours=8))
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    print(f"Fetching daily miku for {today}...")
    client = get_client()
    item = client.get_today()

    # Check if we have a miku for today
    if not item:
        print(f"✗ No daily miku found for {today}", file=sys.stderr)

        # Track failure
        cache_dir = Path.home() / ".cache" / "daily-miku"
        cache_dir.mkdir(parents=True, exist_ok=True)
        failure_file = cache_dir / f"email-failed-{today}.txt"

        # Count failures
        failure_count = 0
        if failure_file.exists():
            content = failure_file.read_text().strip()
            try:
                failure_count = int(content)
            except ValueError:
                failure_count = 0

        failure_count += 1
        failure_file.write_text(str(failure_count))

        print(f"⚠ This is failure #{failure_count} for today")

        # Send warning email on second failure
        if failure_count >= 2:
            print("Sending warning email...")
            if email_module.send_warning_email(
                today, f"No daily miku found for {today}"
            ):
                print("✓ Warning email sent to EMAIL_FROM")
            else:
                print("✗ Failed to send warning email", file=sys.stderr)

        sys.exit(1)

    # Found miku, send email
    formatted = client.format_response(item)
    print(f"✓ Found: {formatted.get('title', 'Untitled')}")
    print("Sending email...")

    if email_module.send_daily_miku_email(formatted):
        print("✓ Email sent successfully!")

        # Clear failure tracking on success
        cache_dir = Path.home() / ".cache" / "daily-miku"
        failure_file = cache_dir / f"email-failed-{today}.txt"
        if failure_file.exists():
            failure_file.unlink()
            print("✓ Cleared failure tracking")
    else:
        print("✗ Failed to send email", file=sys.stderr)
        sys.exit(1)
