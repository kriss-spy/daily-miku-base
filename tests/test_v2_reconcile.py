"""Contract tests for complete tagged-set reconciliation."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from types import TracebackType
from typing import Any

import pytest
import psycopg
import requests

from daily_miku.content_source import (
    InMemoryContentSource,
    RaindropContentSource,
    ScanStatus,
    TaggedItem,
)
from daily_miku.domain import Calendar, FixedClock, SelectionDay
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.ledger.port import LedgerDependencyError, RunStatus
from daily_miku.ledger.postgres import PostgresLedger
from daily_miku.reconcile import Reconciler, ReconciliationDependencyError

pytestmark = pytest.mark.unit

OBSERVED_AT = datetime(2026, 7, 18, 16, 5, tzinfo=timezone.utc)


class FakeResponse:
    """Minimal successful Raindrop response."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class FakeQueryResult:
    """Database rows returned by the transactional adapter fake."""

    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[object, ...]]:
        return [self.row] if self.row is not None else []


class RunDatabase:
    """Transactional fake for reconciliation persistence behavior."""

    def __init__(self) -> None:
        self.records: dict[int, tuple[date, str, datetime]] = {}
        self.runs: dict[int, dict[str, object]] = {}
        self.fail_completion = False

    def connect(self) -> "RunConnection":
        return RunConnection(self)


class RunConnection:
    """Restore all writes when one transaction raises."""

    def __init__(self, database: RunDatabase) -> None:
        self.database = database
        self.snapshot: (
            tuple[dict[int, tuple[date, str, datetime]], dict[int, dict[str, object]]]
            | None
        ) = None

    def __enter__(self) -> "RunConnection":
        self.snapshot = deepcopy((self.database.records, self.database.runs))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            assert self.snapshot is not None
            self.database.records, self.database.runs = self.snapshot

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeQueryResult:
        if query.startswith("INSERT INTO reconciliation_runs"):
            run_id = len(self.database.runs) + 1
            self.database.runs[run_id] = {
                "status": "running",
                "started_at": params[0],
            }
            return FakeQueryResult((run_id,))
        if query.startswith("INSERT INTO selection_ledger"):
            raindrop_id, day, method, observed_at = params
            assert isinstance(raindrop_id, int)
            if raindrop_id in self.database.records:
                return FakeQueryResult()
            assert isinstance(day, date)
            assert isinstance(method, str)
            assert isinstance(observed_at, datetime)
            self.database.records[raindrop_id] = (day, method, observed_at)
            return FakeQueryResult((raindrop_id,))
        if "SET status = 'complete'" in query:
            if self.database.fail_completion:
                raise psycopg.OperationalError("injected completion failure")
            finished_at, discovered, inserted, run_id = params
            assert isinstance(run_id, int)
            run = self.database.runs[run_id]
            if run["status"] != "running":
                return FakeQueryResult()
            run.update(
                status="complete",
                finished_at=finished_at,
                discovered_count=discovered,
                inserted_count=inserted,
            )
            return FakeQueryResult((run_id,))
        if "SET status = %s" in query:
            status, finished_at, discovered, code, message, run_id = params
            assert isinstance(run_id, int)
            run = self.database.runs[run_id]
            if run["status"] != "running":
                return FakeQueryResult()
            run.update(
                status=status,
                finished_at=finished_at,
                discovered_count=discovered,
                error_code=code,
                error_message=message,
            )
            return FakeQueryResult((run_id,))
        raise AssertionError(f"Unexpected SQL: {query}")


def test_raindrop_adapter_reads_every_page_without_last_update_sort() -> None:
    requests_seen: list[dict[str, object]] = []

    def get(url: str, **kwargs: object) -> FakeResponse:
        requests_seen.append(kwargs)
        page = kwargs["params"]["page"]  # type: ignore[index]
        start = int(page) * 50
        items = [{"_id": item_id} for item_id in range(start + 1, 52)][:50]
        return FakeResponse({"count": 51, "items": items})

    scan = RaindropContentSource("token", "daily-miku", get=get).scan_tagged()

    assert scan.status is ScanStatus.COMPLETE
    assert len(scan.items) == 51
    assert [request["params"]["page"] for request in requests_seen] == [0, 1]  # type: ignore[index]
    assert all("sort" not in request["params"] for request in requests_seen)  # type: ignore[operator]


def test_raindrop_adapter_captures_legacy_initialization_fields() -> None:
    def get(url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse(
            {
                "count": 1,
                "items": [
                    {
                        "_id": 7,
                        "lastUpdate": "2026-07-18T16:30:00.000Z",
                        "link": "https://example.com/work",
                        "cover": "https://cdn.example/work.jpg",
                    }
                ],
            }
        )

    scan = RaindropContentSource("token", "tag", get=get).scan_tagged()

    assert scan.items == (
        TaggedItem(
            7,
            datetime(2026, 7, 18, 16, 30, tzinfo=timezone.utc),
            "https://example.com/work",
            "https://cdn.example/work.jpg",
        ),
    )


def test_raindrop_adapter_checks_the_page_after_an_exact_multiple() -> None:
    pages: list[int] = []

    def get(url: str, **kwargs: object) -> FakeResponse:
        page = int(kwargs["params"]["page"])  # type: ignore[index]
        pages.append(page)
        items = [{"_id": item_id} for item_id in range(1, 51)] if page == 0 else []
        return FakeResponse({"count": 50, "items": items})

    scan = RaindropContentSource("token", "tag", get=get).scan_tagged()

    assert scan.status is ScanStatus.COMPLETE
    assert pages == [0, 1]


def test_raindrop_adapter_distinguishes_failed_and_incomplete_scans() -> None:
    def fail_first(url: str, **kwargs: object) -> FakeResponse:
        raise requests.Timeout("secret upstream detail")

    first = RaindropContentSource("token", "tag", get=fail_first).scan_tagged()

    calls = 0

    def fail_second(url: str, **kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise requests.Timeout("secret upstream detail")
        return FakeResponse(
            {"count": 51, "items": [{"_id": item_id} for item_id in range(1, 51)]}
        )

    later = RaindropContentSource("token", "tag", get=fail_second).scan_tagged()

    assert first.status is ScanStatus.FAILED
    assert first.items == ()
    assert later.status is ScanStatus.INCOMPLETE
    assert len(later.items) == 50
    assert "secret" not in str(later)


def test_complete_reconciliation_is_idempotent_and_uses_one_observation_day() -> None:
    ledger = InMemoryLedger()
    source = InMemoryContentSource((TaggedItem(7), TaggedItem(3)))
    reconciler = Reconciler(
        ledger,
        source,
        Calendar.named("Asia/Shanghai"),
        FixedClock(OBSERVED_AT),
    )

    first = reconciler.reconcile()
    second = reconciler.reconcile()

    assert first.status is RunStatus.COMPLETE
    assert first.discovered_count == first.inserted_count == 2
    assert second.status is RunStatus.COMPLETE
    assert second.discovered_count == 2
    assert second.inserted_count == 0
    candidates = ledger.candidates_for(SelectionDay(date(2026, 7, 19)))
    assert [candidate.raindrop_id for candidate in candidates] == [3, 7]
    assert all(candidate.first_observed_at == OBSERVED_AT for candidate in candidates)
    assert [run.status for run in ledger.runs] == [
        RunStatus.COMPLETE,
        RunStatus.COMPLETE,
    ]


@pytest.mark.parametrize(
    ("scan_status", "run_status"),
    [
        (ScanStatus.INCOMPLETE, RunStatus.INCOMPLETE),
        (ScanStatus.FAILED, RunStatus.FAILED),
    ],
)
def test_unsuccessful_scan_records_run_but_no_candidates(
    scan_status: ScanStatus, run_status: RunStatus
) -> None:
    ledger = InMemoryLedger()
    source = InMemoryContentSource((TaggedItem(9),), status=scan_status)
    report = Reconciler(
        ledger,
        source,
        Calendar.named("Asia/Shanghai"),
        FixedClock(OBSERVED_AT),
    ).reconcile()

    assert report.status is run_status
    assert report.discovered_count == 1
    assert report.inserted_count == 0
    assert ledger.candidates_for(SelectionDay(date(2026, 7, 19))) == ()
    assert ledger.runs[0].status is run_status
    assert ledger.runs[0].error_code == "injected_scan_failure"


def test_unsuccessful_scan_reports_failure_to_finalize_run() -> None:
    class UnavailableLedger(InMemoryLedger):
        def finish_reconciliation(self, *args: object, **kwargs: object) -> None:
            raise LedgerDependencyError("injected database failure")

    ledger = UnavailableLedger()
    reconciler = Reconciler(
        ledger,
        InMemoryContentSource(status=ScanStatus.FAILED),
        Calendar.named("Asia/Shanghai"),
        FixedClock(OBSERVED_AT),
    )

    with pytest.raises(ReconciliationDependencyError):
        reconciler.reconcile()

    assert ledger.runs[0].status is RunStatus.RUNNING


def test_removed_tag_does_not_remove_an_existing_ledger_row() -> None:
    ledger = InMemoryLedger()
    source = InMemoryContentSource((TaggedItem(12),))
    reconciler = Reconciler(
        ledger,
        source,
        Calendar.named("Asia/Shanghai"),
        FixedClock(OBSERVED_AT),
    )
    reconciler.reconcile()

    source.items = ()
    reconciler.reconcile()

    assert ledger.candidates_for(SelectionDay(date(2026, 7, 19)))[0].raindrop_id == 12


def test_concurrent_reconciliation_inserts_each_identity_once() -> None:
    ledger = InMemoryLedger()
    source = InMemoryContentSource((TaggedItem(31), TaggedItem(32)))
    reconciler = Reconciler(
        ledger,
        source,
        Calendar.named("Asia/Shanghai"),
        FixedClock(OBSERVED_AT),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        reports = list(executor.map(lambda _: reconciler.reconcile(), range(2)))

    assert sum(report.inserted_count for report in reports) == 2
    assert all(report.status is RunStatus.COMPLETE for report in reports)
    assert len(ledger.candidates_for(SelectionDay(date(2026, 7, 19)))) == 2


def test_postgres_candidate_writes_roll_back_before_failed_run_is_recorded() -> None:
    database = RunDatabase()
    database.fail_completion = True
    reconciler = Reconciler(
        PostgresLedger(database.connect),
        InMemoryContentSource((TaggedItem(21), TaggedItem(22))),
        Calendar.named("Asia/Shanghai"),
        FixedClock(OBSERVED_AT),
    )

    report = reconciler.reconcile()

    assert report.status is RunStatus.FAILED
    assert report.error_code == "ledger_write_failed"
    assert database.records == {}
    assert database.runs[1]["status"] == "failed"
