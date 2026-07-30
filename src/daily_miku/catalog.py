"""Read-only Daily Slot catalog and shared representation."""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlparse

from .content_source import ContentSource, TaggedItem
from .domain import (
    Calendar,
    Clock,
    SelectionDay,
    SlotState,
)
from .selections import (
    MultiDateAssignment,
    SelectionSnapshot,
    SelectionSnapshotCache,
)

MAX_RANGE_DAYS = 366
DEFAULT_PAGE_LIMIT = 24
MAX_PAGE_LIMIT = 100


class InvalidSlotRange(ValueError):
    """A calendar range is reversed or exceeds the response bound."""


class SlotNotFound(LookupError):
    """A selector has no eligible Daily Slot."""


class InvalidCursor(ValueError):
    """An opaque collection cursor is malformed or belongs to another query."""


@dataclass(frozen=True)
class SlotPage:
    """One stable page of complete non-empty Daily Slots."""

    items: tuple[CatalogSlot, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class SlotStatistics:
    """Calendar and cardinality counts over one inclusive interval."""

    first: date
    last: date
    calendar_days: int
    selected_slots: int
    empty_slots: int
    conflict_slots: int
    candidates: int

    def as_dict(self) -> dict[str, object]:
        return {
            "from": self.first.isoformat(),
            "to": self.last.isoformat(),
            "calendar_days": self.calendar_days,
            "selected_slots": self.selected_slots,
            "empty_slots": self.empty_slots,
            "conflict_slots": self.conflict_slots,
            "candidates": self.candidates,
        }


@dataclass(frozen=True)
class SlotItem:
    """One canonical tag assignment with current authoritative content."""

    raindrop_id: int
    title: str
    excerpt: str | None
    source_url: str | None
    domain: str | None
    tags: tuple[str, ...]
    selection_tag: str
    cover_identity: str | None = None


@dataclass(frozen=True)
class CatalogSlot:
    """One read-only Slot derived from current Dated Selection Tags."""

    day: SelectionDay
    items: tuple[SlotItem, ...] = ()

    @property
    def state(self) -> SlotState:
        """Derive state from canonical tag assignment cardinality."""
        count = len(self.items)
        if count == 0:
            return SlotState.EMPTY
        if count == 1:
            return SlotState.SELECTED
        return SlotState.CONFLICT


@dataclass(frozen=True)
class SlotCatalog:
    """Resolve Daily Slots from one complete current Raindrop snapshot per call."""

    calendar: Calendar
    clock: Clock
    content_source: ContentSource
    snapshot_ttl_seconds: float = 30.0
    choose: Callable[[Sequence[SelectionDay]], SelectionDay] = field(
        default=secrets.choice, repr=False
    )
    _snapshots: SelectionSnapshotCache = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_snapshots",
            SelectionSnapshotCache(self.content_source, self.snapshot_ttl_seconds),
        )

    def get_slot(self, day: date) -> CatalogSlot:
        """Resolve a non-future calendar date to its complete Daily Slot."""
        selection_day = self.calendar.require_not_future(day, self.clock)
        return self._slot(selection_day, self._snapshot())

    def today(self) -> CatalogSlot:
        """Resolve today's Slot in the configured calendar timezone."""
        return self.get_slot(self.calendar.today(self.clock).value)

    def latest(self) -> CatalogSlot:
        """Return the latest non-empty Slot, retaining all conflicts."""
        today = self.calendar.today(self.clock)
        snapshot = self._snapshot()
        days = tuple(
            day
            for day in snapshot.by_day
            if day <= today and day not in snapshot.invalid_by_day
        )
        if not days:
            raise SlotNotFound("No non-empty Daily Slot exists")
        return self._slot(max(days), snapshot)

    def random(self) -> CatalogSlot:
        """Choose only from dates having exactly one candidate."""
        today = self.calendar.today(self.clock)
        snapshot = self._snapshot()
        eligible = tuple(
            day
            for day, items in snapshot.by_day.items()
            if day <= today and len(items) == 1 and day not in snapshot.invalid_by_day
        )
        if not eligible:
            raise SlotNotFound("No selected Daily Slot exists")
        selected_day = self.choose(eligible)
        return self._slot(selected_day, snapshot)

    def range(self, first: date, last: date) -> tuple[CatalogSlot, ...]:
        """Return every date in an inclusive ascending bounded range."""
        self.calendar.require_not_future(first, self.clock)
        self.calendar.require_not_future(last, self.clock)
        day_count = (last - first).days + 1
        if day_count <= 0:
            raise InvalidSlotRange("from must not follow to")
        if day_count > MAX_RANGE_DAYS:
            raise InvalidSlotRange("range may contain at most 366 days")
        snapshot = self._snapshot()
        days = (
            SelectionDay(first + timedelta(days=offset)) for offset in range(day_count)
        )
        return tuple(self._slot(day, snapshot) for day in days)

    def search(
        self, query: str, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_LIMIT
    ) -> SlotPage:
        """Search current selected content and retain complete Slots."""
        normalized = query.strip().casefold()
        if not normalized:
            raise ValueError("query must not be blank")
        _validate_limit(limit)
        today = self.calendar.today(self.clock)
        snapshot = self._snapshot()
        grouped = {
            day: items
            for day, items in snapshot.by_day.items()
            if day <= today and day not in snapshot.invalid_by_day
        }
        if not grouped:
            return SlotPage((), None)
        ranked: list[tuple[int, SelectionDay]] = []
        for day, items in grouped.items():
            score = max(_relevance(item, normalized) for item in items)
            if score:
                ranked.append((score, day))
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        offset = _decode_cursor(cursor, normalized)
        if offset > len(ranked):
            raise InvalidCursor("cursor has expired")
        selected = ranked[offset : offset + limit]
        slots = tuple(self._slot(day, snapshot) for _, day in selected)
        next_offset = offset + len(selected)
        next_cursor = (
            _encode_cursor(next_offset, normalized)
            if next_offset < len(ranked)
            else None
        )
        return SlotPage(slots, next_cursor)

    def archive(
        self, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_LIMIT
    ) -> SlotPage:
        """Return non-empty Slots newest-first through a stable opaque cursor."""
        _validate_limit(limit)
        today = self.calendar.today(self.clock)
        snapshot = self._snapshot()
        before = _decode_archive_cursor(cursor)
        days = sorted(
            (
                day
                for day in snapshot.by_day
                if day <= today
                and day not in snapshot.invalid_by_day
                and (before is None or day < before)
            ),
            reverse=True,
        )
        selected = days[:limit]
        slots = tuple(self._slot(day, snapshot) for day in selected)
        next_cursor = (
            _encode_archive_cursor(selected[-1]) if len(days) > len(selected) else None
        )
        return SlotPage(slots, next_cursor)

    def statistics(
        self, first: date | None = None, last: date | None = None
    ) -> SlotStatistics:
        """Aggregate Slot cardinalities without the range representation bound."""
        today = self.calendar.today(self.clock)
        snapshot = self._snapshot()
        current_days = sorted(
            day
            for day in snapshot.by_day
            if day <= today and day not in snapshot.invalid_by_day
        )
        default_first = current_days[0].value if current_days else today.value
        first_date = first or default_first
        last_date = last or today.value
        first_day = self.calendar.require_not_future(first_date, self.clock)
        last_day = self.calendar.require_not_future(last_date, self.clock)
        if first_date > last_date:
            raise InvalidSlotRange("from must not follow to")
        invalid_days = sorted(
            day for day in snapshot.invalid_by_day if first_day <= day <= last_day
        )
        if invalid_days:
            invalid_day = invalid_days[0]
            raise MultiDateAssignment(invalid_day, snapshot.invalid_by_day[invalid_day])
        bounded = {
            day: items
            for day, items in snapshot.by_day.items()
            if first_day <= day <= last_day
        }
        selected = sum(len(items) == 1 for items in bounded.values())
        conflicts = sum(len(items) > 1 for items in bounded.values())
        calendar_days = (last_date - first_date).days + 1
        return SlotStatistics(
            first_date,
            last_date,
            calendar_days,
            selected,
            calendar_days - selected - conflicts,
            conflicts,
            sum(len(items) for items in bounded.values()),
        )

    def _snapshot(self) -> SelectionSnapshot:
        return self._snapshots.get()

    def _slot(self, day: SelectionDay, snapshot: SelectionSnapshot) -> CatalogSlot:
        invalid = snapshot.invalid_by_day.get(day)
        if invalid:
            raise MultiDateAssignment(day, invalid)
        current_items = snapshot.by_day.get(day, ())
        if not current_items:
            return CatalogSlot(day)
        return CatalogSlot(
            day,
            tuple(self._enrich(day, content) for content in current_items),
        )

    @staticmethod
    def _enrich(day: SelectionDay, content: TaggedItem) -> SlotItem:
        return SlotItem(
            raindrop_id=content.raindrop_id,
            title=content.title,
            excerpt=content.excerpt,
            source_url=content.source_url,
            domain=content.domain
            or (
                urlparse(content.source_url).hostname
                if content.source_url is not None
                else None
            ),
            tags=content.tags,
            selection_tag=f"daily-miku-{day.value.isoformat()}",
            cover_identity=content.cover_identity,
        )


def slot_document(slot: CatalogSlot, today: SelectionDay) -> dict[str, object]:
    """Serialize the shared HTTP and CLI Slot representation."""
    day = slot.day.value
    return {
        "date": day.isoformat(),
        "state": slot.state.value,
        "items": [
            {
                "raindrop_id": item.raindrop_id,
                "title": item.title,
                "excerpt": item.excerpt,
                "source_url": item.source_url,
                "image_url": f"/image/{day.isoformat()}",
                "domain": item.domain,
                "tags": list(item.tags),
                "selection_tag": item.selection_tag,
            }
            for item in slot.items
        ],
        "links": {
            "self": f"/api/slots/{day.isoformat()}",
            "previous": (
                f"/api/slots/{(day - timedelta(days=1)).isoformat()}"
                if day > date.min
                else None
            ),
            "next": (
                f"/api/slots/{(day + timedelta(days=1)).isoformat()}"
                if slot.day < today
                else None
            ),
        },
    }


def _validate_limit(limit: int) -> None:
    if limit < 1 or limit > MAX_PAGE_LIMIT:
        raise ValueError("limit must be between 1 and 100")


def _relevance(item: TaggedItem, query: str) -> int:
    title = item.title.casefold()
    excerpt = (item.excerpt or "").casefold()
    source = (item.source_url or "").casefold()
    return title.count(query) * 4 + excerpt.count(query) * 2 + source.count(query)


def _encode_cursor(offset: int, scope: str) -> str:
    payload = json.dumps({"offset": offset, "scope": scope}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None, scope: str) -> int:
    if cursor is None:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.urlsafe_b64decode(padded).decode())
        offset = document["offset"]
        if document != {"offset": offset, "scope": scope} or not isinstance(
            offset, int
        ):
            raise ValueError
        if offset < 0:
            raise ValueError
        return offset
    except (
        ValueError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise InvalidCursor("cursor is malformed") from exc


def _encode_archive_cursor(day: SelectionDay) -> str:
    payload = json.dumps(
        {"before": day.value.isoformat(), "scope": "archive", "v": 1},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def _decode_archive_cursor(cursor: str | None) -> SelectionDay | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        document = json.loads(base64.urlsafe_b64decode(padded).decode())
        before = document["before"]
        if document != {"before": before, "scope": "archive", "v": 1} or not isinstance(
            before, str
        ):
            raise ValueError
        value = date.fromisoformat(before)
        if value.isoformat() != before:
            raise ValueError
        return SelectionDay(value)
    except (
        ValueError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise InvalidCursor("cursor is malformed") from exc
