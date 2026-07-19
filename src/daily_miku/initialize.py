"""Deterministic legacy Selection Ledger initialization."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from urllib.parse import urlsplit, urlunsplit

from .content_source import ContentSource, ScanStatus, TaggedItem
from .domain import Calendar, Clock, RecordingMethod, SelectionDay, SlotCandidate
from .ledger.port import InitializationLedger, LedgerDependencyError

logger = logging.getLogger("daily_miku.v2.initialize")


class InitializationDependencyError(RuntimeError):
    """Initialization could not obtain or persist a complete safe snapshot."""


@dataclass(frozen=True)
class InitializationRow:
    """One proposed legacy ledger row and its derivation evidence."""

    raindrop_id: int
    selection_day: SelectionDay
    last_update: datetime
    candidate: SlotCandidate

    def as_dict(self) -> dict[str, object]:
        """Serialize stable comparison fields for operator review."""
        return {
            "raindrop_id": self.raindrop_id,
            "selection_day": self.selection_day.value.isoformat(),
            "last_update": _utc_text(self.last_update),
            "recording_method": self.candidate.recording_method.value,
        }


@dataclass(frozen=True)
class InitializationConflict:
    """Multiple distinct Raindrop identities assigned to one Selection Day."""

    selection_day: SelectionDay
    raindrop_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        """Serialize one deterministic conflict warning."""
        return {
            "selection_day": self.selection_day.value.isoformat(),
            "raindrop_ids": list(self.raindrop_ids),
        }


@dataclass(frozen=True)
class DuplicateIdentity:
    """A repeated import identity requiring operator review."""

    kind: str
    identity: str
    raindrop_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        """Serialize one deterministic duplicate warning."""
        return {
            "kind": self.kind,
            "identity": self.identity,
            "raindrop_ids": list(self.raindrop_ids),
        }


@dataclass(frozen=True)
class InitializationReport:
    """Stable dry-run or applied initialization result."""

    status: str
    discovered_count: int
    unique_count: int
    existing_count: int
    proposed_rows: tuple[InitializationRow, ...]
    inserted_count: int
    conflicts: tuple[InitializationConflict, ...]
    duplicate_identities: tuple[DuplicateIdentity, ...]

    def as_dict(self) -> dict[str, object]:
        """Serialize the complete operator report."""
        return {
            "status": self.status,
            "discovered": self.discovered_count,
            "unique": self.unique_count,
            "existing": self.existing_count,
            "proposed": [row.as_dict() for row in self.proposed_rows],
            "inserted": self.inserted_count,
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
            "duplicate_identities": [
                warning.as_dict() for warning in self.duplicate_identities
            ],
        }


@dataclass(frozen=True)
class LedgerInitializer:
    """Build and optionally apply one complete legacy snapshot."""

    ledger: InitializationLedger
    content_source: ContentSource
    calendar: Calendar
    clock: Clock

    def initialize(self, *, apply: bool = False) -> InitializationReport:
        """Report deterministic legacy rows and atomically apply when requested."""
        observed_at = self.clock.now().astimezone(timezone.utc)
        scan = self.content_source.scan_tagged()
        if scan.status is not ScanStatus.COMPLETE:
            raise InitializationDependencyError(
                "Raindrop could not provide a complete initialization snapshot."
            )

        ordered_items = sorted(
            scan.items,
            key=lambda item: (
                item.raindrop_id,
                item.last_update or datetime.min.replace(tzinfo=timezone.utc),
                item.source_url or "",
                item.cover_identity or "",
            ),
        )
        missing = [
            item.raindrop_id for item in ordered_items if item.last_update is None
        ]
        if missing:
            raise InitializationDependencyError(
                "Raindrop returned initialization records without lastUpdate."
            )

        unique_items: dict[int, TaggedItem] = {}
        for item in ordered_items:
            unique_items.setdefault(item.raindrop_id, item)
        rows = tuple(self._row(item, observed_at) for item in unique_items.values())
        try:
            existing_ids = self.ledger.recorded_raindrop_ids(tuple(unique_items))
        except LedgerDependencyError as exc:
            logger.exception("initialization_inspection_failed")
            raise InitializationDependencyError(
                "The Selection Ledger could not be inspected."
            ) from exc
        proposed_rows = tuple(
            row for row in rows if row.raindrop_id not in existing_ids
        )
        inserted_count = 0
        if apply and rows:
            try:
                inserted_count = self.ledger.initialize_candidates(
                    tuple((row.selection_day, row.candidate) for row in rows)
                )
            except LedgerDependencyError as exc:
                logger.exception("initialization_commit_failed")
                raise InitializationDependencyError(
                    "The Selection Ledger could not apply initialization."
                ) from exc

        return InitializationReport(
            "applied" if apply else "dry_run",
            len(scan.items),
            len(unique_items),
            len(existing_ids),
            proposed_rows,
            inserted_count,
            _conflicts(rows),
            _duplicates(ordered_items),
        )

    def _row(self, item: TaggedItem, observed_at: datetime) -> InitializationRow:
        assert item.last_update is not None
        candidate = SlotCandidate(item.raindrop_id, RecordingMethod.LEGACY, observed_at)
        return InitializationRow(
            item.raindrop_id,
            self.calendar.selection_day(item.last_update),
            item.last_update,
            candidate,
        )


def _conflicts(
    rows: tuple[InitializationRow, ...],
) -> tuple[InitializationConflict, ...]:
    grouped: dict[SelectionDay, list[int]] = defaultdict(list)
    for row in rows:
        grouped[row.selection_day].append(row.raindrop_id)
    return tuple(
        InitializationConflict(day, tuple(sorted(raindrop_ids)))
        for day, raindrop_ids in sorted(grouped.items())
        if len(raindrop_ids) > 1
    )


def _duplicates(items: list[TaggedItem]) -> tuple[DuplicateIdentity, ...]:
    warnings: list[DuplicateIdentity] = []
    id_counts = Counter(item.raindrop_id for item in items)
    warnings.extend(
        DuplicateIdentity("raindrop_id", str(identity), (identity,) * count)
        for identity, count in id_counts.items()
        if count > 1
    )
    for kind, attribute in (("source", "source_url"), ("cover", "cover_identity")):
        grouped: dict[str, set[int]] = defaultdict(set)
        for item in items:
            raw_identity = getattr(item, attribute)
            if raw_identity:
                grouped[_normalize_url(raw_identity)].add(item.raindrop_id)
        warnings.extend(
            DuplicateIdentity(kind, identity, tuple(sorted(raindrop_ids)))
            for identity, raindrop_ids in grouped.items()
            if len(raindrop_ids) > 1
        )
    return tuple(sorted(warnings, key=lambda warning: (warning.kind, warning.identity)))


def _normalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    port = parts.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, hostname, path, parts.query, ""))


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
