"""Contract tests for durable Daily Slot reads."""

from collections.abc import Sequence
from datetime import date, datetime, timezone
from types import TracebackType

import pytest

from daily_miku.catalog import InvalidSlotRange, SlotCatalog, SlotNotFound
from daily_miku.content_source import InMemoryContentSource, TaggedItem
from daily_miku.domain import (
    Calendar,
    FixedClock,
    FutureSelectionDay,
    RecordingMethod,
    SelectionDay,
    SlotCandidate,
    SlotState,
)
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.ledger.port import Ledger
from daily_miku.ledger.postgres import PostgresLedger

pytestmark = pytest.mark.unit


def candidate(raindrop_id: int) -> SlotCandidate:
    """Build one observed ledger candidate."""
    return SlotCandidate(
        raindrop_id=raindrop_id,
        recording_method=RecordingMethod.OBSERVED,
        first_observed_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )


class FakeResult:
    """Small result object for the Postgres adapter contract test."""

    def __init__(self, rows: Sequence[tuple[object, ...]]) -> None:
        self.rows = list(rows)

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    """Behavioral database fake shared across adapter connections."""

    def __init__(self, records: dict[int, tuple[date, str, datetime]]) -> None:
        self.records = records

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        if query.startswith("INSERT INTO selection_ledger"):
            assert "ON CONFLICT (raindrop_id) DO NOTHING" in query
            raindrop_id, day, method, observed_at = params
            assert isinstance(raindrop_id, int)
            if raindrop_id in self.records:
                return FakeResult([])
            assert isinstance(day, date)
            assert isinstance(method, str)
            assert isinstance(observed_at, datetime)
            self.records[raindrop_id] = (day, method, observed_at)
            return FakeResult([(raindrop_id,)])
        if query.startswith("SELECT raindrop_id"):
            assert "ORDER BY raindrop_id ASC" in query
            (day,) = params
            rows = [
                (raindrop_id, method, observed_at)
                for raindrop_id, (recorded_day, method, observed_at) in sorted(
                    self.records.items()
                )
                if recorded_day == day
            ]
            return FakeResult(rows)
        if query.startswith("SELECT selection_day"):
            assert "ORDER BY selection_day ASC, raindrop_id ASC" in query
            first, last = params
            assert isinstance(first, date)
            assert isinstance(last, date)
            rows = [
                (recorded_day, raindrop_id, method, observed_at)
                for raindrop_id, (recorded_day, method, observed_at) in sorted(
                    self.records.items(), key=lambda row: (row[1][0], row[0])
                )
                if first <= recorded_day <= last
            ]
            return FakeResult(rows)
        raise AssertionError(f"Unexpected SQL: {query}")


@pytest.fixture(params=("memory", "postgres"))
def ledger(request: pytest.FixtureRequest) -> Ledger:
    """Create a fresh implementation of the ledger port."""
    if request.param == "memory":
        return InMemoryLedger()
    records: dict[int, tuple[date, str, datetime]] = {}
    return PostgresLedger(lambda: FakeConnection(records))


class TestLedgerAdapters:
    """Behavior required from every ledger implementation."""

    def test_record_each_identity_once(self, ledger: Ledger) -> None:
        original_day = SelectionDay(date(2026, 7, 18))
        later_day = SelectionDay(date(2026, 7, 19))

        assert ledger.record_candidate(original_day, candidate(20)) is True
        assert ledger.record_candidate(later_day, candidate(20)) is False

        assert ledger.candidates_for(original_day) == (candidate(20),)
        assert ledger.candidates_for(later_day) == ()

    def test_queries_an_inclusive_date_interval(self, ledger: Ledger) -> None:
        first = SelectionDay(date(2026, 7, 17))
        last = SelectionDay(date(2026, 7, 19))
        ledger.record_candidate(last, candidate(9))
        ledger.record_candidate(first, candidate(3))

        assert ledger.candidates_between(first, last) == (
            (first, candidate(3)),
            (last, candidate(9)),
        )


class TestSlotCatalog:
    """Read-only Daily Slot resolution behavior."""

    def test_reads_all_states_without_writing(self) -> None:
        ledger = InMemoryLedger()
        catalog = SlotCatalog(
            ledger,
            Calendar.named("Asia/Shanghai"),
            FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
            InMemoryContentSource((TaggedItem(2), TaggedItem(3), TaggedItem(9))),
        )
        selected_day = SelectionDay(date(2026, 7, 18))
        conflict_day = SelectionDay(date(2026, 7, 19))
        ledger.record_candidate(selected_day, candidate(3))
        ledger.record_candidate(conflict_day, candidate(9))
        ledger.record_candidate(conflict_day, candidate(2))

        empty = catalog.get_slot(date(2026, 7, 17))
        selected = catalog.get_slot(selected_day.value)
        conflict = catalog.get_slot(conflict_day.value)

        assert empty.state is SlotState.EMPTY
        assert selected.state is SlotState.SELECTED
        assert [item.raindrop_id for item in conflict.candidates] == [2, 9]
        assert conflict.state is SlotState.CONFLICT
        assert ledger.write_count == 3

    def test_rejects_future_dates_without_reading_the_ledger(self) -> None:
        ledger = InMemoryLedger()
        catalog = SlotCatalog(
            ledger,
            Calendar.named("Asia/Shanghai"),
            FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
            InMemoryContentSource(),
        )

        with pytest.raises(FutureSelectionDay):
            catalog.get_slot(date(2026, 7, 20))

        assert ledger.read_count == 0

    def test_selectors_ranges_and_current_content_share_one_model(self) -> None:
        now = datetime(2026, 7, 19, tzinfo=timezone.utc)
        ledger = InMemoryLedger()
        source = InMemoryContentSource(
            (
                TaggedItem(
                    3,
                    source_url="https://example.com/three",
                    title="Current title",
                    excerpt="Current excerpt",
                    domain="example.com",
                    tags=("daily-miku", "blue"),
                ),
                TaggedItem(8, source_url="https://example.com/eight", title="Eight"),
                TaggedItem(9, source_url="https://example.com/nine", title="Nine"),
            )
        )
        selected_day = SelectionDay(date(2026, 7, 17))
        conflict_day = SelectionDay(date(2026, 7, 19))
        ledger.record_candidate(selected_day, candidate(3))
        ledger.record_candidate(conflict_day, candidate(8))
        ledger.record_candidate(conflict_day, candidate(9))
        catalog = SlotCatalog(
            ledger,
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
        assert slots[0].items[0].recording_method is RecordingMethod.OBSERVED

    def test_selector_absence_and_range_bounds_are_explicit(self) -> None:
        catalog = SlotCatalog(
            InMemoryLedger(),
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
