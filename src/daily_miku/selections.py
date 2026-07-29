"""Strict Dated Selection Tag parsing and snapshot indexing."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import re
from threading import Lock
from time import monotonic

from .content_source import (
    ContentDependencyError,
    ContentFailure,
    ContentSource,
    ScanStatus,
    TaggedItem,
)
from .domain import SelectionDay

DATED_SELECTION_PREFIX = "daily-miku-"
_CANONICAL_DATED_TAG = re.compile(r"^daily-miku-([0-9]{4}-[0-9]{2}-[0-9]{2})$")


def parse_dated_selection_tag(tag: str) -> SelectionDay | None:
    """Parse only a zero-padded canonical Gregorian Dated Selection Tag."""
    match = _CANONICAL_DATED_TAG.fullmatch(tag)
    if match is None:
        return None
    try:
        value = date.fromisoformat(match.group(1))
    except ValueError:
        return None
    if value.isoformat() != match.group(1):
        return None
    return SelectionDay(value)


@dataclass(frozen=True)
class SelectionSnapshot:
    """One complete current content snapshot indexed by Selection Day."""

    by_day: dict[SelectionDay, tuple[TaggedItem, ...]]
    invalid_by_day: dict[SelectionDay, tuple[MultiDateBookmark, ...]]

    @classmethod
    def from_items(cls, items: tuple[TaggedItem, ...]) -> "SelectionSnapshot":
        """Index valid assignments and mark every day of multi-date items invalid."""
        grouped: dict[SelectionDay, list[TaggedItem]] = defaultdict(list)
        invalid: dict[SelectionDay, list[MultiDateBookmark]] = defaultdict(list)
        for item in items:
            days: tuple[SelectionDay, ...] = tuple(
                sorted(
                    {
                        day
                        for tag in item.tags
                        if (day := parse_dated_selection_tag(tag)) is not None
                    }
                )
            )
            if not days:
                continue
            if len(days) > 1:
                assignment = MultiDateBookmark(
                    item.raindrop_id,
                    tuple(f"{DATED_SELECTION_PREFIX}{day.value.isoformat()}" for day in days),
                )
                for day in days:
                    invalid[day].append(assignment)
                continue
            grouped[next(iter(days))].append(item)
        return cls(
            {
                day: tuple(sorted(values, key=lambda item: item.raindrop_id))
                for day, values in grouped.items()
            },
            {
                day: tuple(sorted(values, key=lambda value: value.raindrop_id))
                for day, values in invalid.items()
            },
        )


@dataclass(frozen=True)
class MultiDateBookmark:
    """One bookmark carrying more than one canonical Dated Selection Tag."""

    raindrop_id: int
    selection_tags: tuple[str, ...]


class MultiDateAssignment(ValueError):
    """A requested Selection Day is named by an invalid multi-date bookmark."""

    def __init__(
        self, day: SelectionDay, assignments: tuple[MultiDateBookmark, ...]
    ) -> None:
        super().__init__("A bookmark has multiple Dated Selection Tags.")
        self.day = day
        self.assignments = assignments


@dataclass
class SelectionSnapshotCache:
    """Coalesce complete account scans and retain one snapshot for a bounded TTL."""

    content_source: ContentSource
    ttl_seconds: float = 30.0
    timer: Callable[[], float] = monotonic

    def __post_init__(self) -> None:
        if self.ttl_seconds < 0:
            raise ValueError("snapshot cache TTL must not be negative")
        self._lock = Lock()
        self._snapshot: SelectionSnapshot | None = None
        self._expires_at = 0.0

    def get(self) -> SelectionSnapshot:
        """Return a fresh complete snapshot without caching failed scans."""
        now = self.timer()
        if self._snapshot is not None and now < self._expires_at:
            return self._snapshot
        with self._lock:
            now = self.timer()
            if self._snapshot is not None and now < self._expires_at:
                return self._snapshot
            scan = self.content_source.scan_tagged()
            if scan.status is not ScanStatus.COMPLETE:
                kind = scan.failure or (
                    ContentFailure.UNAVAILABLE
                    if scan.status is ScanStatus.FAILED
                    else ContentFailure.UPSTREAM
                )
                raise ContentDependencyError(
                    "Raindrop could not provide a complete selection snapshot.", kind
                )
            snapshot = SelectionSnapshot.from_items(scan.items)
            self._snapshot = snapshot
            self._expires_at = now + self.ttl_seconds
            return snapshot
