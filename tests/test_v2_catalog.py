"""Contract tests for durable Daily Slot reads."""

from datetime import date, datetime, timezone

import pytest

from daily_miku.catalog import InvalidSlotRange, SlotCatalog, SlotNotFound
from daily_miku.content_source import InMemoryContentSource, TaggedItem
from daily_miku.domain import (
    Calendar,
    FixedClock,
    FutureSelectionDay,
    SelectionDay,
    SlotState,
)

pytestmark = pytest.mark.unit


class TestSlotCatalog:
    """Read-only Daily Slot resolution behavior."""

    def test_reads_all_states_from_content_source(self) -> None:
        source = InMemoryContentSource(
            (
                TaggedItem(3, tags=("daily-miku-2026-07-18",)),
                TaggedItem(9, tags=("daily-miku-2026-07-19",)),
                TaggedItem(2, tags=("daily-miku-2026-07-19",)),
            )
        )
        catalog = SlotCatalog(
            Calendar.named("Asia/Shanghai"),
            FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
            source,
        )
        selected_day = date(2026, 7, 18)
        conflict_day = date(2026, 7, 19)

        empty = catalog.get_slot(date(2026, 7, 17))
        selected = catalog.get_slot(selected_day)
        conflict = catalog.get_slot(conflict_day)

        assert empty.state is SlotState.EMPTY
        assert selected.state is SlotState.SELECTED
        assert [item.raindrop_id for item in conflict.items] == [2, 9]
        assert conflict.state is SlotState.CONFLICT
        assert source.scan_count == 1

    def test_rejects_future_dates_without_reading_content(self) -> None:
        source = InMemoryContentSource()
        catalog = SlotCatalog(
            Calendar.named("Asia/Shanghai"),
            FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
            source,
        )

        with pytest.raises(FutureSelectionDay):
            catalog.get_slot(date(2026, 7, 20))

        assert source.scan_count == 0

    def test_selectors_ranges_and_current_content_share_one_model(self) -> None:
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        source = InMemoryContentSource(
            (
                TaggedItem(
                    3,
                    source_url="https://example.com/three",
                    title="Current title",
                    excerpt="Current excerpt",
                    domain="example.com",
                    tags=("daily-miku-2026-07-17", "blue"),
                ),
                TaggedItem(
                    8,
                    source_url="https://example.com/eight",
                    title="Eight",
                    tags=("daily-miku-2026-07-19",),
                ),
                TaggedItem(
                    9,
                    source_url="https://example.com/nine",
                    title="Nine",
                    tags=("daily-miku-2026-07-19",),
                ),
            )
        )
        selected_day = SelectionDay(date(2026, 7, 17))
        catalog = SlotCatalog(
            Calendar.named("Asia/Shanghai"),
            FixedClock(now),
            source,
            choose=lambda days: days[0],
        )

        slots = catalog.range(date(2026, 7, 17), date(2026, 7, 19))

        assert [slot.state for slot in slots] == [
            SlotState.SELECTED,
            SlotState.EMPTY,
            SlotState.CONFLICT,
        ]
        assert catalog.latest().state is SlotState.CONFLICT
        assert catalog.random().day == selected_day
        assert slots[0].items[0].title == "Current title"
        assert slots[0].items[0].selection_tag == "daily-miku-2026-07-17"

    def test_archive_cursor_is_stable_when_newer_tags_change(self) -> None:
        source = InMemoryContentSource(
            (
                TaggedItem(1, tags=("daily-miku-2026-07-19",)),
                TaggedItem(2, tags=("daily-miku-2026-07-18",)),
                TaggedItem(3, tags=("daily-miku-2026-07-17",)),
            )
        )
        catalog = SlotCatalog(
            Calendar.named("UTC"),
            FixedClock(datetime(2026, 7, 20, tzinfo=timezone.utc)),
            source,
            snapshot_ttl_seconds=0,
        )

        first = catalog.archive(limit=1)
        source.items = (
            TaggedItem(4, tags=("daily-miku-2026-07-20",)),
            TaggedItem(2, tags=("daily-miku-2026-07-18",)),
            TaggedItem(3, tags=("daily-miku-2026-07-17",)),
        )
        second = catalog.archive(cursor=first.next_cursor, limit=2)

        assert [slot.day.value for slot in second.items] == [
            date(2026, 7, 18),
            date(2026, 7, 17),
        ]

    def test_selector_absence_and_range_bounds_are_explicit(self) -> None:
        catalog = SlotCatalog(
            Calendar.named("Asia/Shanghai"),
            FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
            InMemoryContentSource(),
        )

        with pytest.raises(SlotNotFound):
            catalog.latest()
        with pytest.raises(SlotNotFound):
            catalog.random()
        with pytest.raises(InvalidSlotRange):
            catalog.range(date(2026, 7, 19), date(2026, 7, 18))
        with pytest.raises(InvalidSlotRange):
            catalog.range(date(2025, 7, 18), date(2026, 7, 19))
