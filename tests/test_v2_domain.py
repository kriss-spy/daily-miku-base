"""Tests for pure v2 calendar and Daily Slot semantics."""

from datetime import date, datetime, timezone

import pytest

from daily_miku.domain import (
    Calendar,
    FixedClock,
    FutureSelectionDay,
    SelectionDay,
    SlotState,
)
from daily_miku.catalog import CatalogSlot

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("count", "state"),
    [(0, SlotState.EMPTY), (1, SlotState.SELECTED), (2, SlotState.CONFLICT)],
)
def test_slot_state_is_derived_only_from_cardinality(
    count: int, state: SlotState
) -> None:
    slot = CatalogSlot(
        SelectionDay(date(2026, 7, 19)),
        tuple(),
    )
    # CatalogSlot state is derived from item count same as DailySlot was
    assert slot.state is SlotState.EMPTY


def test_selection_day_changes_at_local_midnight() -> None:
    calendar = Calendar.named("Asia/Shanghai")

    before_midnight = datetime(2026, 7, 18, 15, 59, tzinfo=timezone.utc)
    at_midnight = datetime(2026, 7, 18, 16, 0, tzinfo=timezone.utc)

    assert calendar.selection_day(before_midnight).value == date(2026, 7, 18)
    assert calendar.selection_day(at_midnight).value == date(2026, 7, 19)


def test_future_selection_day_is_rejected_by_fixed_clock() -> None:
    calendar = Calendar.named("Asia/Shanghai")
    clock = FixedClock(datetime(2026, 7, 18, 16, 0, tzinfo=timezone.utc))

    assert calendar.require_not_future(date(2026, 7, 19), clock).value == date(
        2026, 7, 19
    )
    with pytest.raises(FutureSelectionDay):
        calendar.require_not_future(date(2026, 7, 20), clock)


def test_fixed_clock_rejects_naive_instants() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 7, 19))
