"""Read-only Daily Slot catalog and shared representation."""

from __future__ import annotations

import secrets
import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from .content_source import (
    ContentDependencyError,
    ContentFailure,
    ContentSource,
    TaggedItem,
)
from .domain import (
    Calendar,
    Clock,
    RecordingMethod,
    SelectionDay,
    SlotCandidate,
    SlotState,
)
from .ledger.port import Ledger

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
    """One ledger candidate enriched with current authoritative content."""

    raindrop_id: int
    title: str
    excerpt: str | None
    source_url: str | None
    domain: str | None
    tags: tuple[str, ...]
    recording_method: RecordingMethod
    first_observed_at: datetime
    cover_identity: str | None = None


@dataclass(frozen=True)
class CatalogSlot:
    """One read-only Slot combining ledger facts with current content."""

    day: SelectionDay
    candidates: tuple[SlotCandidate, ...] = ()
    items: tuple[SlotItem, ...] = ()

    def __post_init__(self) -> None:
        """Require enriched items to match ledger candidates exactly."""
        candidate_ids = tuple(item.raindrop_id for item in self.candidates)
        item_ids = tuple(item.raindrop_id for item in self.items)
        if candidate_ids != item_ids:
            raise ValueError("Slot items must match ledger candidates")

    @property
    def state(self) -> SlotState:
        """Derive state solely from ledger candidate cardinality."""
        count = len(self.candidates)
        if count == 0:
            return SlotState.EMPTY
        if count == 1:
            return SlotState.SELECTED
        return SlotState.CONFLICT


@dataclass(frozen=True)
class SlotCatalog:
    """Resolve enriched Daily Slots without changing ledger state."""

    ledger: Ledger
    calendar: Calendar
    clock: Clock
    content_source: ContentSource
    choose: Callable[[Sequence[SelectionDay]], SelectionDay] = field(
        default=secrets.choice, repr=False
    )

    def get_slot(self, day: date) -> CatalogSlot:
        """Resolve a non-future calendar date to its complete Daily Slot."""
        selection_day, candidates = self.resolve_candidates(day)
        return self._slot(selection_day, candidates)

    def resolve_candidates(
        self, day: date
    ) -> tuple[SelectionDay, tuple[SlotCandidate, ...]]:
        """Resolve ledger-only Slot identity before optional content enrichment."""
        selection_day = self.calendar.require_not_future(day, self.clock)
        return selection_day, self.ledger.candidates_for(selection_day)

    def today(self) -> CatalogSlot:
        """Resolve today's Slot in the configured calendar timezone."""
        return self.get_slot(self.calendar.today(self.clock).value)

    def latest(self) -> CatalogSlot:
        """Return the latest non-empty Slot, retaining all conflicts."""
        today = self.calendar.today(self.clock)
        rows = self.ledger.candidates_between(SelectionDay(date.min), today)
        if not rows:
            raise SlotNotFound("No non-empty Daily Slot exists")
        latest_day = rows[-1][0]
        candidates = tuple(row[1] for row in rows if row[0] == latest_day)
        return self._slot(latest_day, candidates)

    def random(self) -> CatalogSlot:
        """Choose only from dates having exactly one candidate."""
        today = self.calendar.today(self.clock)
        rows = self.ledger.candidates_between(SelectionDay(date.min), today)
        grouped = self._group(rows)
        eligible = tuple(
            day for day, candidates in grouped.items() if len(candidates) == 1
        )
        if not eligible:
            raise SlotNotFound("No selected Daily Slot exists")
        selected_day = self.choose(eligible)
        return self._slot(selected_day, grouped[selected_day])

    def range(self, first: date, last: date) -> tuple[CatalogSlot, ...]:
        """Return every date in an inclusive ascending bounded range."""
        first_day = self.calendar.require_not_future(first, self.clock)
        last_day = self.calendar.require_not_future(last, self.clock)
        day_count = (last - first).days + 1
        if day_count <= 0:
            raise InvalidSlotRange("from must not follow to")
        if day_count > MAX_RANGE_DAYS:
            raise InvalidSlotRange("range may contain at most 366 days")
        grouped = self._group(self.ledger.candidates_between(first_day, last_day))
        days = (
            SelectionDay(first + timedelta(days=offset)) for offset in range(day_count)
        )
        return tuple(self._slot(day, grouped.get(day, ())) for day in days)

    def search(
        self, query: str, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_LIMIT
    ) -> SlotPage:
        """Search ledger-restricted current content and retain complete Slots."""
        normalized = query.strip().casefold()
        if not normalized:
            raise ValueError("query must not be blank")
        _validate_limit(limit)
        today = self.calendar.today(self.clock)
        rows = self.ledger.candidates_between(SelectionDay(date.min), today)
        grouped = self._group(rows)
        if not rows:
            return SlotPage((), None)
        content = self.content_source.get_items(
            tuple(candidate.raindrop_id for _, candidate in rows)
        )
        by_id = {item.raindrop_id: item for item in content}
        if set(by_id) != {candidate.raindrop_id for _, candidate in rows}:
            raise ContentDependencyError(
                "Raindrop returned incomplete current content.", ContentFailure.UPSTREAM
            )
        ranked: list[tuple[int, SelectionDay]] = []
        for day, candidates in grouped.items():
            score = max(
                _relevance(by_id[candidate.raindrop_id], normalized)
                for candidate in candidates
            )
            if score:
                ranked.append((score, day))
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        offset = _decode_cursor(cursor, normalized)
        if offset > len(ranked):
            raise InvalidCursor("cursor has expired")
        selected = ranked[offset : offset + limit]
        slots = tuple(self._slot(day, grouped[day]) for _, day in selected)
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
        grouped = self._group(
            self.ledger.candidates_between(SelectionDay(date.min), today)
        )
        days = sorted(grouped, reverse=True)
        offset = _decode_cursor(cursor, "archive")
        if offset > len(days):
            raise InvalidCursor("cursor has expired")
        selected = days[offset : offset + limit]
        slots = tuple(self._slot(day, grouped[day]) for day in selected)
        next_offset = offset + len(selected)
        next_cursor = (
            _encode_cursor(next_offset, "archive") if next_offset < len(days) else None
        )
        return SlotPage(slots, next_cursor)

    def statistics(
        self, first: date | None = None, last: date | None = None
    ) -> SlotStatistics:
        """Aggregate Slot cardinalities without the range representation bound."""
        today = self.calendar.today(self.clock)
        rows = self.ledger.candidates_between(SelectionDay(date.min), today)
        default_first = rows[0][0].value if rows else today.value
        first_date = first or default_first
        last_date = last or today.value
        first_day = self.calendar.require_not_future(first_date, self.clock)
        last_day = self.calendar.require_not_future(last_date, self.clock)
        if first_date > last_date:
            raise InvalidSlotRange("from must not follow to")
        bounded = tuple(row for row in rows if first_day <= row[0] <= last_day)
        grouped = self._group(bounded)
        selected = sum(len(candidates) == 1 for candidates in grouped.values())
        conflicts = sum(len(candidates) > 1 for candidates in grouped.values())
        calendar_days = (last_date - first_date).days + 1
        return SlotStatistics(
            first_date,
            last_date,
            calendar_days,
            selected,
            calendar_days - selected - conflicts,
            conflicts,
            len(bounded),
        )

    def _slot(
        self, day: SelectionDay, candidates: tuple[SlotCandidate, ...]
    ) -> CatalogSlot:
        if not candidates:
            return CatalogSlot(day)
        current_items = self.content_source.get_items(
            tuple(candidate.raindrop_id for candidate in candidates)
        )
        content_by_id = {item.raindrop_id: item for item in current_items}
        expected_ids = {candidate.raindrop_id for candidate in candidates}
        if set(content_by_id) != expected_ids:
            raise ContentDependencyError(
                "Raindrop returned incomplete current content.",
                ContentFailure.UPSTREAM,
            )
        return CatalogSlot(
            day,
            candidates,
            tuple(
                self._enrich(candidate, content_by_id[candidate.raindrop_id])
                for candidate in candidates
            ),
        )

    @staticmethod
    def _group(
        rows: tuple[tuple[SelectionDay, SlotCandidate], ...],
    ) -> dict[SelectionDay, tuple[SlotCandidate, ...]]:
        grouped: dict[SelectionDay, list[SlotCandidate]] = {}
        for day, candidate in rows:
            grouped.setdefault(day, []).append(candidate)
        return {day: tuple(candidates) for day, candidates in grouped.items()}

    @staticmethod
    def _enrich(candidate: SlotCandidate, content: TaggedItem) -> SlotItem:
        return SlotItem(
            raindrop_id=candidate.raindrop_id,
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
            recording_method=candidate.recording_method,
            first_observed_at=candidate.first_observed_at,
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
                "recording_method": item.recording_method.value,
                "first_observed_at": item.first_observed_at.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
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
