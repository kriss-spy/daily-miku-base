"""Tests for immutable migration evidence tooling."""

import json
from datetime import date, datetime, timezone

import pytest

from daily_miku.content_source import TaggedItem
from daily_miku.domain import RecordingMethod, SelectionDay, SlotCandidate
from daily_miku.initialize import InitializationReport, InitializationRow
from daily_miku.migration_baseline import build_baseline, compare_retained_routes

pytestmark = pytest.mark.unit


def report() -> InitializationReport:
    instant = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    row = InitializationRow(
        7,
        SelectionDay(date(2026, 7, 18)),
        instant,
        SlotCandidate(7, RecordingMethod.LEGACY, instant),
    )
    return InitializationReport("dry_run", 1, 1, 0, (row,), 0, (), ())


def test_baseline_is_deterministic_complete_and_private(tmp_path) -> None:
    items = (
        TaggedItem(
            7,
            datetime(2026, 7, 18, 12, tzinfo=timezone.utc),
            "https://example.com/7",
            "https://cdn.example/7.png",
            tags=("daily-miku",),
        ),
    )
    evidence = {
        "baseline_date": "2026-07-24",
        "timezone": "Asia/Shanghai",
        "images": {
            "7": {
                "classification": "validated_controlled_mirror",
                "operator": "reviewer",
                "evidence": "controlled image verification report",
                "reviewed_at": "2026-07-24T12:00:00Z",
            }
        },
        "v1_routes": {"2026-07-18": {"selected_id": 7, "status": 307}},
    }

    artifact = build_baseline(items, report(), evidence)
    manifest, checksum = artifact.write_immutable(tmp_path / "baseline.json")

    assert artifact.unresolved == ()
    assert json.loads(manifest.read_text())["review_complete"] is True
    assert checksum.read_text().startswith(artifact.checksum)
    assert manifest.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        artifact.write_immutable(manifest)


def test_baseline_refuses_to_hide_unclassified_images() -> None:
    artifact = build_baseline((TaggedItem(7),), report(), {})

    assert artifact.document["review_complete"] is False
    assert "image:7" in artifact.unresolved


def test_retained_route_comparison_reports_every_changed_identity() -> None:
    mismatches = compare_retained_routes(
        {"2026-07-17": 3, "2026-07-18": 7},
        {"2026-07-17": 3, "2026-07-18": 9, "2026-07-19": 11},
    )

    assert mismatches == ("2026-07-18", "2026-07-19")
