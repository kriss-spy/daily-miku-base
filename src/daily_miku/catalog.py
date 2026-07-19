"""Read-only Daily Slot catalog and shared representation."""

import secrets
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


class InvalidSlotRange(ValueError):
    """A calendar range is reversed or exceeds the response bound."""


class SlotNotFound(LookupError):
    """A selector has no eligible Daily Slot."""


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
        selection_day = self.calendar.require_not_future(day, self.clock)
        return self._slot(selection_day, self.ledger.candidates_for(selection_day))

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
