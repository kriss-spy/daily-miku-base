"""Tests for the v2 operator command surface."""

import json
from datetime import date, datetime, timezone

import pytest

from daily_miku import cli, main
from daily_miku.catalog import SlotCatalog
from daily_miku.cli import read_slot
from daily_miku.content_source import (
    ContentFailure,
    InMemoryContentSource,
    TaggedItem,
)
from daily_miku.config import ConfigurationError
from daily_miku.domain import Calendar, FixedClock

pytestmark = pytest.mark.unit


def slot_catalog(
    *, conflict: bool = False, lookup_failure: ContentFailure | None = None
) -> SlotCatalog:
    """Build an isolated enriched Slot read service."""
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    source_items = [
        TaggedItem(
            4,
            source_url="https://example.com/four",
            title="Four",
            tags=("daily-miku-2026-07-18",),
        )
    ]
    if conflict:
        source_items.append(
            TaggedItem(
                5,
                source_url="https://example.com/five",
                title="Five",
                tags=("daily-miku-2026-07-18",),
            )
        )
    return SlotCatalog(
        Calendar.named("Asia/Shanghai"),
        FixedClock(now),
        InMemoryContentSource(tuple(source_items), lookup_failure=lookup_failure),
    )


def test_slot_read_json_and_human_cover_all_domain_states(
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = slot_catalog()

    assert read_slot(catalog, date(2026, 7, 18), json_output=True) == 0
    selected = json.loads(capsys.readouterr().out)
    assert selected["state"] == "selected"
    assert selected["items"][0]["title"] == "Four"
    assert read_slot(catalog, date(2026, 7, 19)) == 0
    assert "Daily Slot 2026-07-19: empty" in capsys.readouterr().out
    assert read_slot(slot_catalog(conflict=True), date(2026, 7, 18)) == 0
    conflict_output = capsys.readouterr().out
    assert "Daily Slot 2026-07-18: conflict" in conflict_output
    assert "Raindrop ID: 4" in conflict_output
    assert "Raindrop ID: 5" in conflict_output


def test_slot_read_dependency_failure_exits_four(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = read_slot(
        slot_catalog(lookup_failure=ContentFailure.UNAVAILABLE),
        date(2026, 7, 18),
        json_output=True,
    )

    assert exit_code == 4
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "slot_dependency_failed"
    )


def test_slot_read_future_date_is_domain_blocked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = read_slot(slot_catalog(), date(2026, 7, 20), json_output=True)

    assert exit_code == 5
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "future_selection_day"
    )


def test_slot_get_malformed_date_exits_two_before_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_slot_read("2026-2-03", json_output=True)

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invocation_invalid"


def test_slot_read_configuration_failure_exits_three(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_configuration() -> None:
        raise ConfigurationError("Invalid configuration fields: DATABASE_URL")

    monkeypatch.setattr(cli.Settings, "from_environment", fail_configuration)

    exit_code = cli.run_slot_read("2026-07-18", json_output=True)

    assert exit_code == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == (
        "configuration_invalid"
    )


def test_slot_service_construction_failure_exits_one_safely(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.Settings, "from_environment", cli.Settings.in_memory)

    def fail_construction(settings: object) -> None:
        raise RuntimeError("sensitive internal detail")

    monkeypatch.setattr(cli, "build_services", fail_construction)

    exit_code = cli.run_slot_read("2026-07-18", json_output=True)

    assert exit_code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["error"]["code"] == "internal_error"
    assert "sensitive" not in document["error"]["message"]


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["daily-miku", "slot", "today", "--json"], (None, True)),
        (["daily-miku", "slot", "get", "2026-07-18"], ("2026-07-18", False)),
    ],
)
def test_main_dispatches_slot_commands(
    argv: list[str],
    expected: tuple[str | None, bool],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str | None, bool]] = []
    monkeypatch.setattr(
        cli,
        "run_slot_read",
        lambda value, *, json_output=False: calls.append((value, json_output)) or 0,
    )
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 0
    assert calls == [expected]


def test_legacy_ledger_command_surface_is_removed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["daily-miku", "ledger", "reconcile"])

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 1
    assert "Unknown command: ledger" in capsys.readouterr().err
