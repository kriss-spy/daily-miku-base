"""Tests for authoritative Dated Selection Tag Slot resolution."""

from datetime import date, datetime, timezone

import pytest

from daily_miku.catalog import SlotCatalog, SlotNotFound
from daily_miku.content_source import (
    ContentDependencyError,
    InMemoryContentSource,
    ScanStatus,
    TaggedItem,
)
from daily_miku.domain import Calendar, FixedClock, SlotState
from daily_miku.selections import (
    MultiDateAssignment,
    SelectionSnapshotCache,
    parse_dated_selection_tag,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 7, 20, tzinfo=timezone.utc)


def catalog(source: InMemoryContentSource) -> SlotCatalog:
    """Build a deterministic tag-backed catalog."""
    return SlotCatalog(Calendar.named("UTC"), FixedClock(NOW), source)


@pytest.mark.parametrize(
    "tag",
    (
        "daily-miku-2026-7-01",
        "daily-miku-2026-07-1",
        "daily-miku-2026-02-29",
        "daily-miku-2026-01-01-extra",
        "Daily-Miku-2026-01-01",
        "daily-miku-２０２６-０１-０１",
        "daily-miku",
    ),
)
def test_parser_rejects_every_noncanonical_or_invalid_tag(tag: str) -> None:
    assert parse_dated_selection_tag(tag) is None


def test_parser_accepts_only_the_exact_canonical_tag() -> None:
    parsed = parse_dated_selection_tag("daily-miku-2024-02-29")

    assert parsed is not None
    assert parsed.value == date(2024, 2, 29)


def test_malformed_tags_assign_no_slot_and_same_date_items_conflict() -> None:
    source = InMemoryContentSource(
        (
            TaggedItem(1, tags=("daily-miku-2026-7-19",)),
            TaggedItem(2, tags=("daily-miku-2026-07-19",)),
            TaggedItem(3, tags=("daily-miku-2026-07-19",)),
        )
    )

    resolved = catalog(source).get_slot(date(2026, 7, 19))

    assert resolved.state is SlotState.CONFLICT
    assert tuple(item.raindrop_id for item in resolved.items) == (2, 3)
    assert source.scan_count == 1


def test_multi_date_item_is_excluded_and_blocks_every_named_date() -> None:
    source = InMemoryContentSource(
        (
            TaggedItem(
                7,
                tags=("daily-miku-2026-07-18", "daily-miku-2026-07-19"),
            ),
        )
    )
    value = catalog(source)
    for day in (date(2026, 7, 18), date(2026, 7, 19)):
        with pytest.raises(MultiDateAssignment) as caught:
            value.get_slot(day)
        assert caught.value.assignments[0].raindrop_id == 7
        assert caught.value.assignments[0].selection_tags == (
            "daily-miku-2026-07-18",
            "daily-miku-2026-07-19",
        )
    assert source.scan_count == 1


@pytest.mark.parametrize("status", (ScanStatus.INCOMPLETE, ScanStatus.FAILED))
def test_incomplete_discovery_is_never_treated_as_empty(status: ScanStatus) -> None:
    source = InMemoryContentSource(status=status)

    with pytest.raises(ContentDependencyError):
        catalog(source).get_slot(date(2026, 7, 19))


def test_every_catalog_operation_uses_one_complete_snapshot() -> None:
    item = TaggedItem(
        4,
        title="Needle",
        tags=("daily-miku-2026-07-19",),
    )
    operations = (
        lambda value: value.get_slot(date(2026, 7, 19)),
        lambda value: value.today(),
        lambda value: value.latest(),
        lambda value: value.random(),
        lambda value: value.range(date(2026, 7, 18), date(2026, 7, 19)),
        lambda value: value.archive(),
        lambda value: value.search("needle"),
        lambda value: value.statistics(),
    )
    for operation in operations:
        source = InMemoryContentSource((item,))
        operation(catalog(source))
        assert source.scan_count == 1
        assert source.lookup_count == 0


def test_snapshot_cache_expires_and_never_caches_failed_refreshes() -> None:
    current = 0.0
    source = InMemoryContentSource((TaggedItem(4, tags=("daily-miku-2026-07-19",)),))
    snapshots = SelectionSnapshotCache(source, 10, timer=lambda: current)

    assert snapshots.get() is snapshots.get()
    assert source.scan_count == 1
    current = 11
    source.status = ScanStatus.INCOMPLETE
    with pytest.raises(ContentDependencyError):
        snapshots.get()
    with pytest.raises(ContentDependencyError):
        snapshots.get()
    assert source.scan_count == 3


def test_selectors_do_not_treat_multi_date_assignment_as_selected() -> None:
    source = InMemoryContentSource(
        (
            TaggedItem(
                7,
                tags=("daily-miku-2026-07-18", "daily-miku-2026-07-19"),
            ),
        )
    )

    with pytest.raises(SlotNotFound):
        catalog(source).random()
    with pytest.raises(SlotNotFound):
        catalog(source).latest()
