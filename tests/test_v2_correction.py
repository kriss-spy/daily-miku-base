"""Contract tests for audited manual Selection Day corrections."""

from copy import deepcopy
from datetime import date, datetime, timezone
from types import TracebackType

import psycopg
import pytest

from daily_miku.correction import SelectionCorrector
from daily_miku.domain import (
    Calendar,
    FixedClock,
    RecordingMethod,
    SelectionDay,
    SlotCandidate,
)
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.ledger.port import (
    CandidateNotFound,
    CorrectionLedger,
    CorrectionUnchanged,
    LedgerDependencyError,
)
from daily_miku.ledger.postgres import PostgresLedger

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)
ORIGINAL_DAY = SelectionDay(date(2026, 7, 18))
NEW_DAY = SelectionDay(date(2026, 7, 17))


class FakeResult:
    """Minimal database result used by the correction adapter fake."""

    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[object, ...]]:
        return [self.row] if self.row else []


class CorrectionDatabase:
    """Transactional state for the Postgres correction contract."""

    def __init__(self) -> None:
        self.records: dict[int, tuple[date, str, datetime]] = {}
        self.corrections: list[tuple[object, ...]] = []
        self.fail_history = False

    def connect(self) -> "CorrectionConnection":
        return CorrectionConnection(self)


class CorrectionConnection:
    """Rollback fake database state when a transaction raises."""

    def __init__(self, database: CorrectionDatabase) -> None:
        self.database = database
        self.snapshot: object = None

    def __enter__(self) -> "CorrectionConnection":
        self.snapshot = deepcopy((self.database.records, self.database.corrections))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.database.records, self.database.corrections = self.snapshot  # type: ignore[misc]

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        if query.startswith("INSERT INTO selection_ledger"):
            raindrop_id, day, method, observed_at = params
            assert isinstance(raindrop_id, int)
            self.database.records[raindrop_id] = (day, method, observed_at)  # type: ignore[assignment]
            return FakeResult((raindrop_id,))
        if query.startswith("SELECT selection_day"):
            assert "FOR UPDATE" in query
            record = self.database.records.get(int(params[0]))
            return FakeResult(record[:2] if record else None)
        if query.startswith("UPDATE selection_ledger"):
            day, raindrop_id = params
            _, _, observed_at = self.database.records[int(raindrop_id)]
            self.database.records[int(raindrop_id)] = (day, "manual", observed_at)  # type: ignore[assignment]
            return FakeResult()
        if query.startswith("INSERT INTO selection_corrections"):
            if self.database.fail_history:
                raise psycopg.OperationalError("injected history failure")
            self.database.corrections.append(params)
            return FakeResult()
        if query.startswith("SELECT raindrop_id"):
            (day,) = params
            rows = [
                (raindrop_id, method, observed_at)
                for raindrop_id, (recorded_day, method, observed_at) in sorted(
                    self.database.records.items()
                )
                if recorded_day == day
            ]
            result = FakeResult()
            result.fetchall = lambda: rows  # type: ignore[method-assign]
            return result
        raise AssertionError(f"Unexpected SQL: {query}")


@pytest.fixture(params=("memory", "postgres"))
def ledger(request: pytest.FixtureRequest) -> CorrectionLedger:
    """Provide both correction adapter implementations."""
    if request.param == "memory":
        return InMemoryLedger()
    return PostgresLedger(CorrectionDatabase().connect)


def candidate(raindrop_id: int) -> SlotCandidate:
    """Build one originally observed candidate."""
    return SlotCandidate(raindrop_id, RecordingMethod.OBSERVED, NOW)


def test_adapters_correct_and_audit_the_same_candidate(
    ledger: CorrectionLedger,
) -> None:
    ledger.record_candidate(ORIGINAL_DAY, candidate(7))
    ledger.record_candidate(NEW_DAY, candidate(8))

    correction = ledger.correct_candidate(
        7, NEW_DAY, "Archived message dated 2026-07-17", "operator", NOW
    )

    assert correction.raindrop_id == 7
    assert correction.former_day == ORIGINAL_DAY
    assert correction.new_day == NEW_DAY
    assert correction.former_method is RecordingMethod.OBSERVED
    assert correction.new_method is RecordingMethod.MANUAL
    assert correction.reason == "Archived message dated 2026-07-17"
    assert correction.operator == "operator"
    assert ledger.candidates_for(ORIGINAL_DAY) == ()
    assert [item.raindrop_id for item in ledger.candidates_for(NEW_DAY)] == [7, 8]
    assert all(
        item.recording_method is RecordingMethod.MANUAL
        for item in ledger.candidates_for(NEW_DAY)
        if item.raindrop_id == 7
    )
    if isinstance(ledger, InMemoryLedger):
        assert ledger.corrections == [correction]


def test_adapters_reject_missing_and_unchanged_candidates(
    ledger: CorrectionLedger,
) -> None:
    ledger.record_candidate(ORIGINAL_DAY, candidate(7))

    with pytest.raises(CandidateNotFound):
        ledger.correct_candidate(99, NEW_DAY, "evidence", "operator", NOW)
    with pytest.raises(CorrectionUnchanged):
        ledger.correct_candidate(7, ORIGINAL_DAY, "evidence", "operator", NOW)


def test_corrector_rejects_blank_reason_and_future_day() -> None:
    ledger = InMemoryLedger()
    ledger.record_candidate(ORIGINAL_DAY, candidate(7))
    corrector = SelectionCorrector(
        ledger, Calendar.named("Asia/Shanghai"), FixedClock(NOW), "operator"
    )

    with pytest.raises(ValueError, match="reason"):
        corrector.correct(7, NEW_DAY.value, "  ")
    with pytest.raises(ValueError, match="future"):
        corrector.correct(7, date(2026, 7, 20), "evidence")

    assert ledger.candidates_for(ORIGINAL_DAY) == (candidate(7),)
    assert ledger.corrections == []


def test_postgres_rolls_back_ledger_when_audit_insert_fails() -> None:
    database = CorrectionDatabase()
    ledger = PostgresLedger(database.connect)
    ledger.record_candidate(ORIGINAL_DAY, candidate(7))
    database.fail_history = True

    with pytest.raises(LedgerDependencyError):
        ledger.correct_candidate(7, NEW_DAY, "evidence", "operator", NOW)

    assert ledger.candidates_for(ORIGINAL_DAY) == (candidate(7),)
    assert ledger.candidates_for(NEW_DAY) == ()
    assert database.corrections == []


def test_postgres_persists_complete_audit_history() -> None:
    database = CorrectionDatabase()
    ledger = PostgresLedger(database.connect)
    ledger.record_candidate(ORIGINAL_DAY, candidate(7))

    ledger.correct_candidate(
        7, NEW_DAY, "Archived message dated 2026-07-17", "operator", NOW
    )

    assert database.corrections == [
        (
            7,
            ORIGINAL_DAY.value,
            NEW_DAY.value,
            "observed",
            "Archived message dated 2026-07-17",
            "operator",
            NOW,
        )
    ]
