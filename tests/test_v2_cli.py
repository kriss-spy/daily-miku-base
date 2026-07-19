"""Tests for the v2 operator command surface."""

import json
from datetime import datetime, timezone

import pytest

from daily_miku import cli, main
from daily_miku.cli import reconcile_ledger
from daily_miku.content_source import InMemoryContentSource, ScanStatus, TaggedItem
from daily_miku.domain import Calendar, FixedClock
from daily_miku.ledger.memory import InMemoryLedger
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
