"""CLI commands for daily-miku-base."""

import json
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import email as email_module
from .catalog import CatalogSlot, SlotCatalog, slot_document
from .config import (
    ConfigurationError,
    ImageSettings,
    InitializationSettings,
    LedgerSettings,
    Settings,
)
from .content_source import ContentDependencyError, RaindropContentSource
from .correction import SelectionCorrector
from .domain import Calendar, FutureSelectionDay, SystemClock
from .delivery import DeliveryBlocked, DeliveryDependencyError
from .initialize import InitializationDependencyError, LedgerInitializer
from .images import ImageBlocked, ImageDependencyError, ImagePipeline
from .images.blob import VercelBlobStore
from .images.publisher import RaindropCoverPublisher
from .images.store import PostgresImageRepository
from .ledger.postgres import PostgresLedger
from .ledger.port import (
    CandidateNotFound,
    CorrectionRecord,
    CorrectionUnchanged,
    LedgerDependencyError,
    RunStatus,
)
from .raindrop import get_client
from .reconcile import Reconciler, ReconciliationDependencyError
from .services import build_services

logger = logging.getLogger("daily_miku.v2.cli")


def _error_document(code: str, message: str) -> dict[str, object]:
    return {
        "status": "failed",
        "error": {"code": code, "message": message, "details": {}},
    }


def _correction_document(record: CorrectionRecord) -> dict[str, object]:
    return {
        "status": "corrected",
        "raindrop_id": record.raindrop_id,
        "former_selection_day": record.former_day.value.isoformat(),
        "new_selection_day": record.new_day.value.isoformat(),
        "former_recording_method": record.former_method.value,
        "new_recording_method": record.new_method.value,
        "reason": record.reason,
        "operator": record.operator,
        "corrected_at": record.corrected_at.isoformat().replace("+00:00", "Z"),
    }


def run_email_send(
    requested_date: date | None,
    *,
    force: bool = False,
    json_output: bool = False,
) -> int:
    """Reconcile and deliver one image-required Daily Slot."""
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
        ReconciliationDependencyError,
        LedgerDependencyError,
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
    except (LedgerDependencyError, ContentDependencyError):
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
    except (LedgerDependencyError, ContentDependencyError):
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


def initialize_ledger(
    initializer: LedgerInitializer,
    *,
    apply: bool = False,
    json_output: bool = False,
) -> int:
    """Run legacy initialization and render its complete review report."""
    try:
        report = initializer.initialize(apply=apply)
    except InitializationDependencyError:
        message = "Legacy initialization could not access a complete safe snapshot."
        if json_output:
            print(
                json.dumps(_error_document("initialization_dependency_failed", message))
            )
        else:
            print(message, file=sys.stderr)
        return 4
    except Exception:
        message = "An unexpected legacy initialization failure occurred."
        if json_output:
            print(json.dumps(_error_document("internal_error", message)))
        else:
            print(message, file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(report.as_dict()))
        return 0

    action = "Applied" if apply else "Dry run"
    print(
        f"{action}: discovered {report.discovered_count}, "
        f"unique {report.unique_count}, existing {report.existing_count}, "
        f"proposed {len(report.proposed_rows)}, inserted {report.inserted_count}."
    )
    for row in report.proposed_rows:
        print(
            f"  Raindrop {row.raindrop_id}: {row.selection_day.value} "
            f"(legacy, lastUpdate {_utc_timestamp(row.last_update)})"
        )
    for conflict in report.conflicts:
        identities = ", ".join(str(value) for value in conflict.raindrop_ids)
        print(f"  Conflict {conflict.selection_day.value}: {identities}")
    for warning in report.duplicate_identities:
        identities = ", ".join(str(value) for value in warning.raindrop_ids)
        print(f"  Duplicate {warning.kind} {warning.identity}: {identities}")
    return 0


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def run_ledger_initialize(*, apply: bool = False, json_output: bool = False) -> int:
    """Build configured services and run legacy initialization."""
    try:
        settings = InitializationSettings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    ledger = PostgresLedger.from_url(
        settings.database_url.get_secret_value(), local_pool=not settings.serverless
    )
    initializer = LedgerInitializer(
        ledger,
        RaindropContentSource(settings.raindrop_token.get_secret_value(), settings.tag),
        Calendar.named(settings.timezone_name),
        SystemClock(),
    )
    return initialize_ledger(
        initializer,
        apply=apply,
        json_output=json_output,
    )


def correct_selection_day(
    corrector: SelectionCorrector,
    raindrop_id: int,
    new_date: date,
    reason: str,
    *,
    json_output: bool = False,
) -> int:
    """Apply one correction and render safe audit facts."""
    try:
        record = corrector.correct(raindrop_id, new_date, reason)
    except CorrectionUnchanged as exc:
        document = {
            "status": "unchanged",
            "raindrop_id": raindrop_id,
            "selection_day": new_date.isoformat(),
        }
        if json_output:
            print(json.dumps(document))
        else:
            print(str(exc))
        return 0
    except (CandidateNotFound, FutureSelectionDay) as exc:
        if json_output:
            print(json.dumps(_error_document("correction_blocked", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 5
    except ValueError as exc:
        if json_output:
            print(json.dumps(_error_document("invocation_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except LedgerDependencyError:
        message = "The Selection Ledger could not apply the correction."
        if json_output:
            print(json.dumps(_error_document("ledger_dependency_failed", message)))
        else:
            print(message, file=sys.stderr)
        return 4
    except Exception:
        message = "An unexpected correction failure occurred."
        if json_output:
            print(json.dumps(_error_document("internal_error", message)))
        else:
            print(message, file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps(_correction_document(record)))
    else:
        print(
            f"Corrected Raindrop {record.raindrop_id}: "
            f"{record.former_day.value} ({record.former_method.value}) -> "
            f"{record.new_day.value} ({record.new_method.value})."
        )
        print(f"Reason: {record.reason}")
        print(
            f"Operator: {record.operator}; corrected at {record.corrected_at.isoformat()}."
        )
    return 0


def run_ledger_correct(
    raindrop_id_value: str,
    date_value: str,
    reason: str,
    *,
    json_output: bool = False,
) -> int:
    """Validate arguments, build configured services, and apply a correction."""
    try:
        raindrop_id = int(raindrop_id_value)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
            raise ValueError
        new_date = date.fromisoformat(date_value)
        if raindrop_id <= 0 or not reason.strip():
            raise ValueError
    except ValueError:
        message = (
            "RAINDROP_ID must be positive, DATE must be YYYY-MM-DD, and "
            "--reason must not be blank."
        )
        if json_output:
            print(json.dumps(_error_document("invocation_invalid", message)))
        else:
            print(message, file=sys.stderr)
        return 2

    try:
        settings = LedgerSettings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(json.dumps(_error_document("configuration_invalid", str(exc))))
        else:
            print(str(exc), file=sys.stderr)
        return 3
    ledger = PostgresLedger.from_url(
        settings.database_url.get_secret_value(), local_pool=not settings.serverless
    )
    corrector = SelectionCorrector(
        ledger,
        Calendar.named(settings.timezone_name),
        SystemClock(),
        settings.operator,
    )
    return correct_selection_day(
        corrector,
        raindrop_id,
        new_date,
        reason,
        json_output=json_output,
    )


def reconcile_ledger(reconciler: Reconciler, *, json_output: bool = False) -> int:
    """Run shared reconciliation and render its safe operator report."""
    try:
        report = reconciler.reconcile()
    except ReconciliationDependencyError:
        document = {
            "status": "failed",
            "error": {
                "code": "reconciliation_dependency_failed",
                "message": "Reconciliation could not access required storage.",
                "details": {},
            },
        }
        if json_output:
            print(json.dumps(document))
        else:
            print(
                "Reconciliation could not access required storage.",
                file=sys.stderr,
            )
        return 4

    if json_output:
        print(json.dumps(report.as_dict()))
    elif report.status is RunStatus.COMPLETE:
        print(
            f"Reconciliation complete: discovered {report.discovered_count}, "
            f"inserted {report.inserted_count} (run {report.run_id})."
        )
    else:
        print(
            f"Reconciliation {report.status.value}: {report.error_message}",
            file=sys.stderr,
        )
    return 0 if report.status is RunStatus.COMPLETE else 4


def run_ledger_reconcile(*, json_output: bool = False) -> int:
    """Build configured services and execute the reconciliation command."""
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        if json_output:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "error": {
                            "code": "configuration_invalid",
                            "message": str(exc),
                            "details": {},
                        },
                    }
                )
            )
        else:
            print(str(exc), file=sys.stderr)
        return 3
    return reconcile_ledger(
        build_services(settings).reconciler, json_output=json_output
    )


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
    ledger = PostgresLedger.from_url(
        settings.database_url.get_secret_value(), local_pool=not settings.serverless
    )
    source = RaindropContentSource(
        settings.raindrop_token.get_secret_value(), settings.tag
    )
    return ImagePipeline(
        SlotCatalog(ledger, calendar, clock, source),
        PostgresImageRepository.from_url(
            settings.database_url.get_secret_value(), local_pool=not settings.serverless
        ),
        VercelBlobStore(settings.blob_read_write_token.get_secret_value()),
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
