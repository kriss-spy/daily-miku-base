"""Tests for the v2 operator command surface."""

import json
from datetime import date, datetime, timezone

import pytest

from daily_miku import cli, main
from daily_miku.catalog import SlotCatalog
from daily_miku.cli import (
    correct_selection_day,
    initialize_ledger,
    read_slot,
    reconcile_ledger,
)
from daily_miku.content_source import (
    ContentFailure,
    InMemoryContentSource,
    ScanStatus,
    TaggedItem,
)
from daily_miku.config import ConfigurationError
from daily_miku.correction import SelectionCorrector
from daily_miku.domain import (
    Calendar,
    FixedClock,
    RecordingMethod,
    SelectionDay,
    SlotCandidate,
)
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.initialize import LedgerInitializer
from daily_miku.reconcile import Reconciler

pytestmark = pytest.mark.unit


def reconciler(status: ScanStatus = ScanStatus.COMPLETE) -> Reconciler:
    """Build an isolated command service."""
    return Reconciler(
        InMemoryLedger(),
        InMemoryContentSource((TaggedItem(4),), status=status),
        Calendar.named("Asia/Shanghai"),
        FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
    )


def initializer() -> LedgerInitializer:
    """Build an isolated legacy initialization service."""
    return LedgerInitializer(
        InMemoryLedger(),
        InMemoryContentSource(
            (
                TaggedItem(
                    4,
                    datetime(2026, 7, 18, 12, tzinfo=timezone.utc),
                    "https://example.com/work",
                    "https://cdn.example/work.jpg",
                ),
            )
        ),
        Calendar.named("Asia/Shanghai"),
        FixedClock(datetime(2026, 7, 19, tzinfo=timezone.utc)),
    )


def slot_catalog(
    *, conflict: bool = False, lookup_failure: ContentFailure | None = None
) -> SlotCatalog:
    """Build an isolated enriched Slot read service."""
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    ledger = InMemoryLedger()
    source_items = [TaggedItem(4, source_url="https://example.com/four", title="Four")]
    ledger.record_candidate(
        SelectionDay(date(2026, 7, 18)),
        SlotCandidate(4, RecordingMethod.OBSERVED, now),
    )
    if conflict:
        ledger.record_candidate(
            SelectionDay(date(2026, 7, 18)),
            SlotCandidate(5, RecordingMethod.MANUAL, now),
        )
        source_items.append(
            TaggedItem(5, source_url="https://example.com/five", title="Five")
        )
    return SlotCatalog(
        ledger,
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


def test_ledger_initialize_json_reports_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = initialize_ledger(initializer(), json_output=True)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "dry_run",
        "discovered": 1,
        "unique": 1,
        "existing": 0,
        "proposed": [
            {
                "raindrop_id": 4,
                "selection_day": "2026-07-18",
                "last_update": "2026-07-18T12:00:00Z",
                "recording_method": "legacy",
            }
        ],
        "inserted": 0,
        "conflicts": [],
        "duplicate_identities": [],
    }


def test_main_dispatches_ledger_initialize_apply_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bool, bool]] = []
    monkeypatch.setattr(
        cli,
        "run_ledger_initialize",
        lambda *, apply=False, json_output=False: calls.append((apply, json_output))
        or 0,
    )
    monkeypatch.setattr(
        "sys.argv", ["daily-miku", "ledger", "initialize", "--apply", "--json"]
    )

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 0
    assert calls == [(True, True)]


def test_ledger_reconcile_json_reports_complete_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = reconcile_ledger(reconciler(), json_output=True)

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "run_id": 1,
        "status": "complete",
        "discovered": 1,
        "inserted": 1,
    }


def test_ledger_reconcile_incomplete_scan_is_dependency_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = reconcile_ledger(reconciler(ScanStatus.INCOMPLETE), json_output=True)

    assert exit_code == 4
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "incomplete"
    assert document["inserted"] == 0
    assert document["error"]["code"] == "injected_scan_failure"
    assert document["error"]["details"] == {}


def test_main_dispatches_ledger_reconcile_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        cli,
        "run_ledger_reconcile",
        lambda *, json_output=False: calls.append(json_output) or 0,
    )
    monkeypatch.setattr("sys.argv", ["daily-miku", "ledger", "reconcile", "--json"])

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 0
    assert calls == [True]


def test_invalid_json_invocation_emits_json_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["daily-miku", "ledger", "reconcile", "--json", "--bad"]
    )

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 2
    document = json.loads(capsys.readouterr().out)
    assert document["error"]["code"] == "invocation_invalid"
    assert document["error"]["details"] == {}


def test_ledger_correct_json_reports_safe_audit_facts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    ledger = InMemoryLedger()
    ledger.record_candidate(
        SelectionDay(date(2026, 7, 18)),
        SlotCandidate(4, RecordingMethod.OBSERVED, now),
    )
    corrector = SelectionCorrector(
        ledger, Calendar.named("Asia/Shanghai"), FixedClock(now), "test-operator"
    )

    exit_code = correct_selection_day(
        corrector,
        4,
        date(2026, 7, 17),
        "Archived message",
        json_output=True,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "status": "corrected",
        "raindrop_id": 4,
        "former_selection_day": "2026-07-18",
        "new_selection_day": "2026-07-17",
        "former_recording_method": "observed",
        "new_recording_method": "manual",
        "reason": "Archived message",
        "operator": "test-operator",
        "corrected_at": "2026-07-19T00:00:00Z",
    }


def test_ledger_correct_future_date_is_domain_blocked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    corrector = SelectionCorrector(
        InMemoryLedger(),
        Calendar.named("Asia/Shanghai"),
        FixedClock(now),
        "test-operator",
    )

    exit_code = correct_selection_day(
        corrector, 4, date(2026, 7, 20), "evidence", json_output=True
    )

    assert exit_code == 5
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "correction_blocked"


def test_ledger_correct_same_date_is_successful_noop(
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    ledger = InMemoryLedger()
    day = SelectionDay(date(2026, 7, 18))
    ledger.record_candidate(day, SlotCandidate(4, RecordingMethod.OBSERVED, now))
    corrector = SelectionCorrector(
        ledger, Calendar.named("Asia/Shanghai"), FixedClock(now), "test-operator"
    )

    exit_code = correct_selection_day(
        corrector, 4, day.value, "evidence", json_output=True
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "unchanged",
        "raindrop_id": 4,
        "selection_day": "2026-07-18",
    }
    assert ledger.corrections == []


def test_main_dispatches_ledger_correct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str, bool]] = []
    monkeypatch.setattr(
        cli,
        "run_ledger_correct",
        lambda item, day, reason, *, json_output=False: calls.append(
            (item, day, reason, json_output)
        )
        or 0,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "daily-miku",
            "ledger",
            "correct",
            "4",
            "2026-07-17",
            "--reason",
            "Archived message",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 0
    assert calls == [("4", "2026-07-17", "Archived message", True)]


@pytest.mark.parametrize(
    "argv",
    [
        ["daily-miku", "ledger", "correct", "4", "2026-07-17"],
        [
            "daily-miku",
            "ledger",
            "correct",
            "4",
            "2026-07-17",
            "--reason",
            "evidence",
            "--bad",
            "--json",
        ],
    ],
)
def test_invalid_ledger_correct_shape_exits_two(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 2
