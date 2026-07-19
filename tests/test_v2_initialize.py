"""Contract tests for legacy Selection Ledger initialization."""

from copy import deepcopy
from datetime import date, datetime, timezone
from types import TracebackType

import psycopg
import pytest

from daily_miku.content_source import InMemoryContentSource, ScanStatus, TaggedItem
from daily_miku.domain import (
    Calendar,
    FixedClock,
    RecordingMethod,
    SelectionDay,
    SlotCandidate,
)
from daily_miku.initialize import InitializationDependencyError, LedgerInitializer
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.ledger.port import LedgerDependencyError
from daily_miku.ledger.postgres import PostgresLedger

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)


def item(
    raindrop_id: int,
    last_update: str,
    *,
    source_url: str | None = None,
    cover_identity: str | None = None,
) -> TaggedItem:
    """Build one legacy tagged item from an API timestamp."""
    return TaggedItem(
        raindrop_id,
        datetime.fromisoformat(last_update.replace("Z", "+00:00")),
        source_url,
        cover_identity,
    )


def test_dry_run_is_deterministic_complete_and_read_only() -> None:
    ledger = InMemoryLedger()
    source = InMemoryContentSource(
        (
            item(
                9,
                "2026-07-18T16:30:00Z",
                source_url="HTTPS://Example.com/work/",
                cover_identity="https://cdn.example/image#fragment",
            ),
            item(
                3,
                "2026-07-18T15:30:00Z",
                source_url="https://example.com/work",
                cover_identity="https://cdn.example/image",
            ),
            item(3, "2026-07-18T15:30:00Z"),
        )
    )
    initializer = LedgerInitializer(
        ledger, source, Calendar.named("Asia/Shanghai"), FixedClock(NOW)
    )

    first = initializer.initialize()
    second = initializer.initialize()

    assert first == second
    assert first.status == "dry_run"
    assert first.discovered_count == 3
    assert first.unique_count == 2
    assert first.existing_count == 0
    assert [row.as_dict() for row in first.proposed_rows] == [
        {
            "raindrop_id": 3,
            "selection_day": "2026-07-18",
            "last_update": "2026-07-18T15:30:00Z",
            "recording_method": "legacy",
        },
        {
            "raindrop_id": 9,
            "selection_day": "2026-07-19",
            "last_update": "2026-07-18T16:30:00Z",
            "recording_method": "legacy",
        },
    ]
    assert [warning.as_dict() for warning in first.duplicate_identities] == [
        {
            "kind": "cover",
            "identity": "https://cdn.example/image",
            "raindrop_ids": [3, 9],
        },
        {"kind": "raindrop_id", "identity": "3", "raindrop_ids": [3, 3]},
        {
            "kind": "source",
            "identity": "https://example.com/work",
            "raindrop_ids": [3, 9],
        },
    ]
    assert first.conflicts == ()
    assert ledger.write_count == 0
    assert ledger.runs == []


def test_apply_is_atomic_idempotent_and_keeps_accepted_conflicts_visible() -> None:
    ledger = InMemoryLedger()
    source = InMemoryContentSource(
        (
            item(8, "2026-07-18T12:00:00Z"),
            item(2, "2026-07-18T13:00:00Z"),
        )
    )
    initializer = LedgerInitializer(
        ledger, source, Calendar.named("Asia/Shanghai"), FixedClock(NOW)
    )

    applied = initializer.initialize(apply=True)
    repeated = initializer.initialize()

    day = SelectionDay(date(2026, 7, 18))
    assert applied.status == "applied"
    assert applied.inserted_count == 2
    assert applied.conflicts[0].as_dict() == {
        "selection_day": "2026-07-18",
        "raindrop_ids": [2, 8],
    }
    assert repeated.proposed_rows == ()
    assert repeated.existing_count == 2
    assert repeated.conflicts == applied.conflicts
    assert [candidate.raindrop_id for candidate in ledger.candidates_for(day)] == [2, 8]
    assert all(
        candidate.recording_method is RecordingMethod.LEGACY
        for candidate in ledger.candidates_for(day)
    )


def test_apply_rejects_an_existing_row_that_does_not_match_the_snapshot() -> None:
    ledger = InMemoryLedger()
    day = SelectionDay(date(2026, 7, 18))
    ledger.record_candidate(day, SlotCandidate(8, RecordingMethod.OBSERVED, NOW))
    initializer = LedgerInitializer(
        ledger,
        InMemoryContentSource((item(8, "2026-07-18T12:00:00Z"),)),
        Calendar.named("Asia/Shanghai"),
        FixedClock(NOW),
    )

    with pytest.raises(InitializationDependencyError):
        initializer.initialize(apply=True)

    assert ledger.candidates_for(day)[0].recording_method is RecordingMethod.OBSERVED


@pytest.mark.parametrize("status", [ScanStatus.INCOMPLETE, ScanStatus.FAILED])
def test_unsuccessful_or_invalid_scans_never_write(status: ScanStatus) -> None:
    ledger = InMemoryLedger()
    initializer = LedgerInitializer(
        ledger,
        InMemoryContentSource((item(1, "2026-07-18T12:00:00Z"),), status=status),
        Calendar.named("Asia/Shanghai"),
        FixedClock(NOW),
    )

    with pytest.raises(InitializationDependencyError):
        initializer.initialize(apply=True)

    missing_timestamp = LedgerInitializer(
        ledger,
        InMemoryContentSource((TaggedItem(2),)),
        Calendar.named("Asia/Shanghai"),
        FixedClock(NOW),
    )
    with pytest.raises(InitializationDependencyError):
        missing_timestamp.initialize(apply=True)

    assert ledger.write_count == 0
    assert ledger.runs == []


class InitializationDatabase:
    """Transactional fake used to prove all-or-nothing legacy inserts."""

    def __init__(self) -> None:
        self.records: dict[int, tuple[date, str, datetime]] = {}
        self.fail_on_id: int | None = None
        self.race_on_id: int | None = None

    def connect(self) -> "InitializationConnection":
        return InitializationConnection(self)


class InitializationResult:
    """Minimal query result for initialization adapter tests."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class InitializationConnection:
    """Restore fake database contents when its transaction fails."""

    def __init__(self, database: InitializationDatabase) -> None:
        self.database = database
        self.snapshot: dict[int, tuple[date, str, datetime]] = {}

    def __enter__(self) -> "InitializationConnection":
        self.snapshot = deepcopy(self.database.records)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.database.records = self.snapshot

    def execute(
        self, query: str, params: tuple[object, ...] = ()
    ) -> InitializationResult:
        if query.startswith("SELECT raindrop_id FROM selection_ledger"):
            requested = set(params[0])  # type: ignore[arg-type]
            return InitializationResult(
                [
                    (raindrop_id,)
                    for raindrop_id in sorted(requested & self.database.records.keys())
                ]
            )
        if query.startswith("INSERT INTO selection_ledger"):
            raindrop_id, day, method, observed_at = params
            assert isinstance(raindrop_id, int)
            assert isinstance(day, date)
            assert isinstance(method, str)
            assert isinstance(observed_at, datetime)
            if raindrop_id == self.database.fail_on_id:
                raise psycopg.OperationalError("injected initialization failure")
            if raindrop_id == self.database.race_on_id:
                self.database.records[raindrop_id] = (
                    day,
                    RecordingMethod.OBSERVED.value,
                    observed_at,
                )
                return InitializationResult()
            if raindrop_id in self.database.records:
                return InitializationResult()
            self.database.records[raindrop_id] = (day, method, observed_at)  # type: ignore[assignment]
            return InitializationResult([(raindrop_id,)])
        if query.startswith("SELECT selection_day, recording_method"):
            raindrop_id = params[0]
            assert isinstance(raindrop_id, int)
            record = self.database.records.get(raindrop_id)
            return InitializationResult([record[:2]] if record else [])
        raise AssertionError(f"Unexpected SQL: {query}")


def test_postgres_apply_rolls_back_the_complete_initialization() -> None:
    database = InitializationDatabase()
    database.fail_on_id = 2
    ledger = PostgresLedger(database.connect)
    rows = (
        (
            SelectionDay(date(2026, 7, 18)),
            SlotCandidate(1, RecordingMethod.LEGACY, NOW),
        ),
        (
            SelectionDay(date(2026, 7, 18)),
            SlotCandidate(2, RecordingMethod.LEGACY, NOW),
        ),
    )

    with pytest.raises(LedgerDependencyError):
        ledger.initialize_candidates(rows)

    assert database.records == {}


def test_postgres_apply_rejects_a_concurrent_nonlegacy_insert() -> None:
    database = InitializationDatabase()
    database.race_on_id = 2
    ledger = PostgresLedger(database.connect)
    rows = (
        (
            SelectionDay(date(2026, 7, 18)),
            SlotCandidate(1, RecordingMethod.LEGACY, NOW),
        ),
        (
            SelectionDay(date(2026, 7, 18)),
            SlotCandidate(2, RecordingMethod.LEGACY, NOW),
        ),
    )

    with pytest.raises(LedgerDependencyError):
        ledger.initialize_candidates(rows)

    assert database.records == {}
