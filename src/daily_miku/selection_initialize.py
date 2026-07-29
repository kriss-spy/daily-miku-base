"""Safe initialization of generic Raindrop selections as dated tags."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
import re
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

GENERIC_SELECTION_TAG = "daily-miku"
DATED_SELECTION_PREFIX = f"{GENERIC_SELECTION_TAG}-"
_CANONICAL_DATED_TAG = re.compile(r"^daily-miku-(\d{4}-\d{2}-\d{2})$")


class SelectionInitializationDependencyError(RuntimeError):
    """Raindrop could not provide or mutate verified initialization state."""


@dataclass(frozen=True)
class SelectionTagItem:
    """Raindrop fields required to initialize one selection safely."""

    raindrop_id: int
    last_update: datetime
    tags: tuple[str, ...]
    source_url: str | None = None
    cover_identity: str | None = None

    def __post_init__(self) -> None:
        """Validate durable identity and concurrency evidence."""
        if self.raindrop_id <= 0:
            raise ValueError("raindrop_id must be positive")
        if self.last_update.tzinfo is None or self.last_update.utcoffset() is None:
            raise ValueError("last_update must be timezone-aware")


class SelectionTagStore(Protocol):
    """Raindrop operations required by dated-tag initialization."""

    def scan_generic(self) -> tuple[SelectionTagItem, ...]:
        """Return a complete snapshot of generic and dated selection tags."""
        ...

    def get(self, raindrop_id: int) -> SelectionTagItem:
        """Refetch one current item by identity."""
        ...

    def update_tags(self, raindrop_id: int, tags: tuple[str, ...]) -> None:
        """Replace tags on one Raindrop using its supported update operation."""
        ...


@dataclass(frozen=True)
class TagInitializationProposal:
    """One immutable dry-run snapshot and its proposed canonical tag."""

    raindrop_id: int
    last_update: datetime
    selection_day: date
    current_tags: tuple[str, ...]
    proposed_tag: str

    def as_dict(self) -> dict[str, object]:
        """Serialize operator-review and drift-check evidence."""
        return {
            "raindrop_id": self.raindrop_id,
            "last_update": _utc_text(self.last_update),
            "selection_day": self.selection_day.isoformat(),
            "current_tags": list(self.current_tags),
            "proposed_tag": self.proposed_tag,
        }


@dataclass(frozen=True)
class TagInitializationResult:
    """Independent mutation outcome for one proposal."""

    raindrop_id: int
    status: str
    tags: tuple[str, ...] | None = None

    def as_dict(self) -> dict[str, object]:
        """Serialize a safe per-item outcome."""
        document: dict[str, object] = {
            "raindrop_id": self.raindrop_id,
            "status": self.status,
        }
        if self.tags is not None:
            document["tags"] = list(self.tags)
        return document


@dataclass(frozen=True)
class TagDiagnostic:
    """Stable diagnostic with the affected Raindrop identities and evidence."""

    identity: str
    raindrop_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        """Serialize one diagnostic."""
        return {"identity": self.identity, "raindrop_ids": list(self.raindrop_ids)}


@dataclass(frozen=True)
class SelectionInitializationReport:
    """Complete dry-run, applied, blocked, or incomplete operator report."""

    status: str
    discovered_count: int
    proposals: tuple[TagInitializationProposal, ...]
    results: tuple[TagInitializationResult, ...]
    malformed_dated_tags: tuple[TagDiagnostic, ...]
    multi_date_assignments: tuple[TagDiagnostic, ...]
    duplicate_identities: tuple[TagDiagnostic, ...]
    same_date_conflicts: tuple[TagDiagnostic, ...]

    @property
    def applied_count(self) -> int:
        """Return the number of successful mutations."""
        return sum(result.status == "applied" for result in self.results)

    def as_dict(self) -> dict[str, object]:
        """Serialize the complete stable report."""
        return {
            "status": self.status,
            "discovered": self.discovered_count,
            "proposed": [proposal.as_dict() for proposal in self.proposals],
            "applied": self.applied_count,
            "results": [result.as_dict() for result in self.results],
            "diagnostics": {
                "malformed_dated_tags": [
                    value.as_dict() for value in self.malformed_dated_tags
                ],
                "multi_date_assignments": [
                    value.as_dict() for value in self.multi_date_assignments
                ],
                "duplicate_identities": [
                    value.as_dict() for value in self.duplicate_identities
                ],
                "same_date_conflicts": [
                    value.as_dict() for value in self.same_date_conflicts
                ],
            },
        }


@dataclass(frozen=True)
class SelectionTagInitializer:
    """Plan and optionally apply resumable Raindrop tag initialization."""

    store: SelectionTagStore
    timezone_name: str

    def initialize(self, *, apply: bool = False) -> SelectionInitializationReport:
        """Scan exact generic tags and mutate only verified snapshots."""
        items = tuple(
            sorted(
                self.store.scan_generic(),
                key=lambda item: (item.raindrop_id, item.last_update, item.tags),
            )
        )
        exact_items = tuple(
            item for item in items if GENERIC_SELECTION_TAG in item.tags
        )
        unique_items: dict[int, SelectionTagItem] = {}
        for item in exact_items:
            unique_items.setdefault(item.raindrop_id, item)
        proposals = tuple(self._proposal(item) for item in unique_items.values())
        diagnostics = _diagnostics(items, proposals)
        if not apply:
            return SelectionInitializationReport(
                "dry_run", len(exact_items), proposals, (), *diagnostics
            )

        results: list[TagInitializationResult] = []
        dependency_failed = False
        for index, proposal in enumerate(proposals):
            try:
                current = self.store.get(proposal.raindrop_id)
            except SelectionInitializationDependencyError:
                results.append(TagInitializationResult(proposal.raindrop_id, "failed"))
                results.extend(
                    TagInitializationResult(pending.raindrop_id, "not_attempted")
                    for pending in proposals[index + 1 :]
                )
                dependency_failed = True
                break
            if (
                current.last_update != proposal.last_update
                or current.tags != proposal.current_tags
            ):
                results.append(
                    TagInitializationResult(
                        proposal.raindrop_id, "blocked_drift", current.tags
                    )
                )
                continue
            desired_tags = _desired_tags(current.tags, proposal.proposed_tag)
            try:
                self.store.update_tags(proposal.raindrop_id, desired_tags)
            except SelectionInitializationDependencyError:
                results.append(TagInitializationResult(proposal.raindrop_id, "failed"))
                results.extend(
                    TagInitializationResult(pending.raindrop_id, "not_attempted")
                    for pending in proposals[index + 1 :]
                )
                dependency_failed = True
                break
            results.append(
                TagInitializationResult(proposal.raindrop_id, "applied", desired_tags)
            )

        status = "incomplete" if dependency_failed else "applied"
        if not dependency_failed and any(
            result.status == "blocked_drift" for result in results
        ):
            status = "blocked"
        return SelectionInitializationReport(
            status, len(exact_items), proposals, tuple(results), *diagnostics
        )

    def _proposal(self, item: SelectionTagItem) -> TagInitializationProposal:
        selection_day = item.last_update.astimezone(ZoneInfo(self.timezone_name)).date()
        return TagInitializationProposal(
            item.raindrop_id,
            item.last_update,
            selection_day,
            item.tags,
            f"{DATED_SELECTION_PREFIX}{selection_day.isoformat()}",
        )


@dataclass
class InMemorySelectionTagStore:
    """Mutable, failure-injectable Raindrop fake for isolated tests."""

    items: list[SelectionTagItem] = field(default_factory=list)
    fail_scan: bool = False
    fail_get_ids: set[int] = field(default_factory=set)
    fail_update_ids: set[int] = field(default_factory=set)
    updates: list[tuple[int, tuple[str, ...]]] = field(default_factory=list)

    def scan_generic(self) -> tuple[SelectionTagItem, ...]:
        """Return selection-tag matches or inject a dependency failure."""
        if self.fail_scan:
            raise SelectionInitializationDependencyError("Raindrop scan failed")
        return tuple(
            item
            for item in self.items
            if any(
                tag == GENERIC_SELECTION_TAG or tag.startswith(DATED_SELECTION_PREFIX)
                for tag in item.tags
            )
        )

    def get(self, raindrop_id: int) -> SelectionTagItem:
        """Return current fake state by identity."""
        if raindrop_id in self.fail_get_ids:
            raise SelectionInitializationDependencyError("Raindrop lookup failed")
        for item in self.items:
            if item.raindrop_id == raindrop_id:
                return item
        raise SelectionInitializationDependencyError("Raindrop item is unavailable")

    def update_tags(self, raindrop_id: int, tags: tuple[str, ...]) -> None:
        """Replace current fake tags or inject a dependency failure."""
        if raindrop_id in self.fail_update_ids:
            raise SelectionInitializationDependencyError("Raindrop update failed")
        matched = False
        for index, item in enumerate(self.items):
            if item.raindrop_id == raindrop_id:
                self.items[index] = replace(item, tags=tags)
                matched = True
        if not matched:
            raise SelectionInitializationDependencyError("Raindrop item is unavailable")
        self.updates.append((raindrop_id, tags))


def _desired_tags(current: tuple[str, ...], proposed: str) -> tuple[str, ...]:
    preserved = tuple(
        tag
        for tag in current
        if tag != GENERIC_SELECTION_TAG and _dated_tag_date(tag) is None
    )
    return (*preserved, proposed)


def _diagnostics(
    items: tuple[SelectionTagItem, ...],
    proposals: tuple[TagInitializationProposal, ...],
) -> tuple[
    tuple[TagDiagnostic, ...],
    tuple[TagDiagnostic, ...],
    tuple[TagDiagnostic, ...],
    tuple[TagDiagnostic, ...],
]:
    malformed: list[TagDiagnostic] = []
    multi_date: list[TagDiagnostic] = []
    for item in items:
        valid_dates: set[date] = set()
        for tag in item.tags:
            if not tag.startswith(DATED_SELECTION_PREFIX):
                continue
            parsed = _dated_tag_date(tag)
            if parsed is None:
                malformed.append(TagDiagnostic(tag, (item.raindrop_id,)))
            else:
                valid_dates.add(parsed)
        if len(valid_dates) > 1:
            multi_date.append(
                TagDiagnostic(
                    ",".join(sorted(value.isoformat() for value in valid_dates)),
                    (item.raindrop_id,),
                )
            )
    return (
        tuple(
            sorted(malformed, key=lambda value: (value.identity, value.raindrop_ids))
        ),
        tuple(sorted(multi_date, key=lambda value: value.raindrop_ids)),
        _duplicate_diagnostics(items),
        _same_date_diagnostics(items, proposals),
    )


def _dated_tag_date(tag: str) -> date | None:
    match = _CANONICAL_DATED_TAG.fullmatch(tag)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def _duplicate_diagnostics(
    items: Iterable[SelectionTagItem],
) -> tuple[TagDiagnostic, ...]:
    values = tuple(items)
    diagnostics: list[TagDiagnostic] = []
    counts = Counter(item.raindrop_id for item in values)
    diagnostics.extend(
        TagDiagnostic(f"raindrop_id:{identity}", (identity,) * count)
        for identity, count in counts.items()
        if count > 1
    )
    for kind, attribute in (("source", "source_url"), ("cover", "cover_identity")):
        grouped: dict[str, set[int]] = defaultdict(set)
        for item in values:
            raw = getattr(item, attribute)
            if raw:
                grouped[_normalize_url(raw)].add(item.raindrop_id)
        diagnostics.extend(
            TagDiagnostic(f"{kind}:{identity}", tuple(sorted(raindrop_ids)))
            for identity, raindrop_ids in grouped.items()
            if len(raindrop_ids) > 1
        )
    return tuple(sorted(diagnostics, key=lambda value: value.identity))


def _same_date_diagnostics(
    items: tuple[SelectionTagItem, ...],
    proposals: tuple[TagInitializationProposal, ...],
) -> tuple[TagDiagnostic, ...]:
    grouped: dict[date, set[int]] = defaultdict(set)
    proposed_ids = {proposal.raindrop_id for proposal in proposals}
    for item in items:
        if item.raindrop_id in proposed_ids:
            continue
        for tag in item.tags:
            selection_day = _dated_tag_date(tag)
            if selection_day is not None:
                grouped[selection_day].add(item.raindrop_id)
    for proposal in proposals:
        grouped[proposal.selection_day].add(proposal.raindrop_id)
    return tuple(
        TagDiagnostic(day.isoformat(), tuple(sorted(raindrop_ids)))
        for day, raindrop_ids in sorted(grouped.items())
        if len(raindrop_ids) > 1
    )


def _normalize_url(value: str) -> str:
    stripped = value.strip()
    try:
        parts = urlsplit(stripped)
    except ValueError:
        return stripped
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        return stripped
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"
    return urlunsplit((scheme, hostname, parts.path.rstrip("/"), parts.query, ""))


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
