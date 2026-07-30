"""Focused tests for resumable Raindrop dated-tag initialization."""

from dataclasses import replace
from datetime import datetime

import pytest

from daily_miku.selection_initialize import (
    InMemorySelectionTagStore,
    SelectionTagInitializer,
    SelectionTagItem,
)

pytestmark = pytest.mark.unit


def item(
    raindrop_id: int,
    timestamp: str,
    tags: tuple[str, ...] = ("daily-miku",),
    *,
    source: str | None = None,
    cover: str | None = None,
) -> SelectionTagItem:
    """Build one fake Raindrop selection."""
    return SelectionTagItem(
        raindrop_id,
        datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
        tags,
        source,
        cover,
    )


def test_dry_run_uses_timezone_and_exact_generic_matching() -> None:
    store = InMemorySelectionTagStore(
        [
            item(1, "2026-07-18T15:59:59Z", ("daily-miku", "keep")),
            item(2, "2026-07-18T16:00:00Z"),
            item(3, "2026-07-18T16:00:00Z", ("daily-miku-old",)),
        ]
    )

    report = SelectionTagInitializer(store, "Asia/Shanghai").initialize()

    assert report.status == "dry_run"
    assert [proposal.selection_day.isoformat() for proposal in report.proposals] == [
        "2026-07-18",
        "2026-07-19",
    ]
    assert report.proposals[0].current_tags == ("daily-miku", "keep")
    assert store.updates == []


def test_diagnostics_cover_malformed_multi_date_duplicates_and_conflicts() -> None:
    store = InMemorySelectionTagStore(
        [
            item(
                1,
                "2026-07-18T12:00:00Z",
                (
                    "daily-miku",
                    "daily-miku-nope",
                    "daily-miku-2026-07-17",
                    "daily-miku-2026-07-18",
                ),
                source="HTTPS://example.test/work/",
            ),
            item(
                2,
                "2026-07-18T13:00:00Z",
                source="https://example.test/work",
            ),
            item(2, "2026-07-18T13:00:00Z"),
            item(
                3,
                "2026-07-20T13:00:00Z",
                ("daily-miku-2026-07-18", "daily-miku-invalid"),
            ),
        ]
    )

    report = SelectionTagInitializer(store, "UTC").initialize()

    assert {value.identity for value in report.malformed_dated_tags} == {
        "daily-miku-invalid",
        "daily-miku-nope",
    }
    assert report.multi_date_assignments[0].raindrop_ids == (1,)
    assert {value.identity for value in report.duplicate_identities} == {
        "raindrop_id:2",
        "source:https://example.test/work",
    }
    assert report.same_date_conflicts[0].raindrop_ids == (1, 2, 3)


def test_malformed_duplicate_identity_url_remains_reportable() -> None:
    store = InMemorySelectionTagStore(
        [
            item(1, "2026-07-18T12:00:00Z", source="https://example.test:bad/x"),
            item(2, "2026-07-19T12:00:00Z", source="https://example.test:bad/x"),
        ]
    )

    report = SelectionTagInitializer(store, "UTC").initialize()

    assert report.duplicate_identities[0].raindrop_ids == (1, 2)


def test_invalid_ipv6_identity_remains_reportable() -> None:
    store = InMemorySelectionTagStore(
        [
            item(1, "2026-07-18T12:00:00Z", source="https://[broken"),
            item(2, "2026-07-19T12:00:00Z", source="https://[broken"),
        ]
    )

    report = SelectionTagInitializer(store, "UTC").initialize()

    assert report.duplicate_identities[0].raindrop_ids == (1, 2)


def test_apply_preserves_unrelated_tags_and_replaces_canonical_selection_tags() -> None:
    store = InMemorySelectionTagStore(
        [
            item(
                1,
                "2026-07-18T12:00:00Z",
                (
                    "art",
                    "daily-miku",
                    "daily-miku-bad",
                    "daily-miku-2020-01-01",
                    "vocaloid",
                ),
            )
        ]
    )

    report = SelectionTagInitializer(store, "UTC").initialize(apply=True)

    assert report.status == "applied"
    assert store.get(1).tags == (
        "art",
        "daily-miku-bad",
        "vocaloid",
        "daily-miku-2026-07-18",
    )
    assert report.results[0].status == "applied"


class DriftingStore(InMemorySelectionTagStore):
    """Change tags between scan and mandatory apply refetch."""

    def get(self, raindrop_id: int) -> SelectionTagItem:
        current = super().get(raindrop_id)
        drifted = replace(current, tags=(*current.tags, "concurrent"))
        self.items[0] = drifted
        return drifted


def test_apply_blocks_drift_without_mutation() -> None:
    store = DriftingStore([item(1, "2026-07-18T12:00:00Z")])

    report = SelectionTagInitializer(store, "UTC").initialize(apply=True)

    assert report.status == "blocked"
    assert report.results[0].status == "blocked_drift"
    assert store.updates == []


def test_partial_failure_stops_and_rerun_resumes_idempotently() -> None:
    store = InMemorySelectionTagStore(
        [
            item(1, "2026-07-18T12:00:00Z"),
            item(2, "2026-07-19T12:00:00Z"),
            item(3, "2026-07-20T12:00:00Z"),
        ],
        fail_update_ids={2},
    )
    initializer = SelectionTagInitializer(store, "UTC")

    first = initializer.initialize(apply=True)
    store.fail_update_ids.clear()
    resumed = initializer.initialize(apply=True)
    repeated = initializer.initialize(apply=True)

    assert first.status == "incomplete"
    assert [result.status for result in first.results] == [
        "applied",
        "failed",
        "not_attempted",
    ]
    assert [proposal.raindrop_id for proposal in resumed.proposals] == [2, 3]
    assert resumed.applied_count == 2
    assert repeated.proposals == ()
    assert repeated.applied_count == 0
    assert len(store.updates) == 3
