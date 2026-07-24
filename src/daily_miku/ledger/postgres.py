"""Postgres Selection Ledger adapter."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg_pool import PoolTimeout

from ..domain import RecordingMethod, SelectionDay, SlotCandidate
from .database import ConnectionFactory, postgres_connections
from .port import (
    CandidateNotFound,
    CorrectionRecord,
    CorrectionUnchanged,
    LedgerDependencyError,
    RunStatus,
)


@dataclass(frozen=True)
class PostgresLedger:
    """Persist ledger candidates through short-lived pooled connections."""

    connection_factory: ConnectionFactory

    @classmethod
    def from_url(
        cls, database_url: str, *, local_pool: bool = False
    ) -> "PostgresLedger":
        """Build the adapter for a pooled Postgres URL."""
        return cls(postgres_connections(database_url, local_pool=local_pool))

    def record_candidate(self, day: SelectionDay, candidate: SlotCandidate) -> bool:
        """Insert an unseen identity without changing an existing record."""
        with self.connection_factory() as connection:
            row = connection.execute(
                "INSERT INTO selection_ledger "
                "(raindrop_id, selection_day, recording_method, first_observed_at) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (raindrop_id) DO NOTHING RETURNING raindrop_id",
                (
                    candidate.raindrop_id,
                    day.value,
                    candidate.recording_method.value,
                    candidate.first_observed_at,
                ),
            ).fetchone()
        return row is not None

    def candidates_for(self, day: SelectionDay) -> tuple[SlotCandidate, ...]:
        """Read one complete Slot in deterministic identity order."""
        try:
            with self.connection_factory() as connection:
                rows = connection.execute(
                    "SELECT raindrop_id, recording_method, first_observed_at "
                    "FROM selection_ledger WHERE selection_day = %s "
                    "ORDER BY raindrop_id ASC",
                    (day.value,),
                ).fetchall()
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not read Selection Ledger") from exc
        return tuple(
            SlotCandidate(
                raindrop_id=int(row[0]),
                recording_method=RecordingMethod(str(row[1])),
                first_observed_at=row[2],
            )
            for row in rows
        )

    def candidates_between(
        self, first: SelectionDay, last: SelectionDay
    ) -> tuple[tuple[SelectionDay, SlotCandidate], ...]:
        """Read an inclusive date interval in stable calendar order."""
        try:
            with self.connection_factory() as connection:
                rows = connection.execute(
                    "SELECT selection_day, raindrop_id, recording_method, "
                    "first_observed_at FROM selection_ledger "
                    "WHERE selection_day BETWEEN %s AND %s "
                    "ORDER BY selection_day ASC, raindrop_id ASC",
                    (first.value, last.value),
                ).fetchall()
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not read Selection Ledger") from exc
        return tuple(
            (
                SelectionDay(row[0]),
                SlotCandidate(int(row[1]), RecordingMethod(str(row[2])), row[3]),
            )
            for row in rows
        )

    def reconciliation_runs(self) -> tuple[dict[str, object], ...]:
        """Return recent durable runs newest-first for health reporting."""
        try:
            with self.connection_factory() as connection:
                rows = connection.execute(
                    "SELECT run_id, status, started_at, finished_at, "
                    "discovered_count, inserted_count, error_code "
                    "FROM reconciliation_runs ORDER BY run_id DESC LIMIT 20"
                ).fetchall()
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError(
                "Could not read reconciliation history"
            ) from exc
        return tuple(
            {
                "run_id": int(row[0]),
                "status": str(row[1]),
                "started_at": row[2],
                "finished_at": row[3],
                "discovered_count": int(row[4]),
                "inserted_count": int(row[5]),
                "error_code": row[6],
            }
            for row in rows
        )

    def schema_version(self) -> int:
        """Read the latest applied migration version."""
        try:
            with self.connection_factory() as connection:
                row = connection.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                ).fetchone()
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not read schema version") from exc
        return int(row[0]) if row else 0

    def recorded_raindrop_ids(self, raindrop_ids: Sequence[int]) -> frozenset[int]:
        """Read requested identities that already exist in the ledger."""
        if not raindrop_ids:
            return frozenset()
        try:
            with self.connection_factory() as connection:
                rows = connection.execute(
                    "SELECT raindrop_id FROM selection_ledger "
                    "WHERE raindrop_id = ANY(%s) ORDER BY raindrop_id ASC",
                    (list(raindrop_ids),),
                ).fetchall()
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not inspect Selection Ledger") from exc
        return frozenset(int(row[0]) for row in rows)

    def initialize_candidates(
        self, rows: Sequence[tuple[SelectionDay, SlotCandidate]]
    ) -> int:
        """Insert the approved legacy set in one database transaction."""
        inserted_count = 0
        try:
            with self.connection_factory() as connection:
                for day, candidate in rows:
                    row = connection.execute(
                        "INSERT INTO selection_ledger "
                        "(raindrop_id, selection_day, recording_method, "
                        "first_observed_at) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (raindrop_id) DO NOTHING RETURNING raindrop_id",
                        (
                            candidate.raindrop_id,
                            day.value,
                            candidate.recording_method.value,
                            candidate.first_observed_at,
                        ),
                    ).fetchone()
                    if row is None:
                        existing = connection.execute(
                            "SELECT selection_day, recording_method "
                            "FROM selection_ledger WHERE raindrop_id = %s FOR UPDATE",
                            (candidate.raindrop_id,),
                        ).fetchone()
                        if existing is None or (
                            existing[0] != day.value
                            or str(existing[1]) != RecordingMethod.LEGACY.value
                        ):
                            raise LedgerDependencyError(
                                f"Raindrop {candidate.raindrop_id} changed during "
                                "initialization"
                            )
                    inserted_count += row is not None
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError(
                "Could not initialize Selection Ledger"
            ) from exc
        return inserted_count

    def correct_candidate(
        self,
        raindrop_id: int,
        new_day: SelectionDay,
        reason: str,
        operator: str,
        corrected_at: datetime,
    ) -> CorrectionRecord:
        """Move one candidate and append history in one database transaction."""
        try:
            with self.connection_factory() as connection:
                row = connection.execute(
                    "SELECT selection_day, recording_method FROM selection_ledger "
                    "WHERE raindrop_id = %s FOR UPDATE",
                    (raindrop_id,),
                ).fetchone()
                if row is None:
                    raise CandidateNotFound(f"Raindrop {raindrop_id} is not recorded")
                former_day = SelectionDay(row[0])
                former_method = RecordingMethod(str(row[1]))
                if former_day == new_day:
                    raise CorrectionUnchanged(
                        f"Raindrop {raindrop_id} is already assigned to {new_day.value}"
                    )
                connection.execute(
                    "UPDATE selection_ledger SET selection_day = %s, "
                    "recording_method = 'manual' WHERE raindrop_id = %s",
                    (new_day.value, raindrop_id),
                )
                connection.execute(
                    "INSERT INTO selection_corrections "
                    "(raindrop_id, former_selection_day, new_selection_day, "
                    "former_recording_method, new_recording_method, reason, "
                    "operator, corrected_at) VALUES (%s, %s, %s, %s, "
                    "'manual', %s, %s, %s)",
                    (
                        raindrop_id,
                        former_day.value,
                        new_day.value,
                        former_method.value,
                        reason,
                        operator,
                        corrected_at,
                    ),
                )
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not correct Selection Day") from exc
        return CorrectionRecord(
            raindrop_id,
            former_day,
            new_day,
            former_method,
            reason,
            operator,
            corrected_at,
        )

    def start_reconciliation(self, started_at: datetime) -> int:
        """Create a durable running reconciliation record."""
        try:
            with self.connection_factory() as connection:
                row = connection.execute(
                    "INSERT INTO reconciliation_runs (status, started_at) "
                    "VALUES ('running', %s) RETURNING run_id",
                    (started_at,),
                ).fetchone()
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not start reconciliation") from exc
        if row is None:
            raise LedgerDependencyError(
                "Database did not return a reconciliation run ID"
            )
        return int(row[0])

    def complete_reconciliation(
        self,
        run_id: int,
        day: SelectionDay,
        candidates: tuple[SlotCandidate, ...],
        finished_at: datetime,
    ) -> int:
        """Atomically insert candidates and mark one running run complete."""
        inserted_count = 0
        try:
            with self.connection_factory() as connection:
                for candidate in candidates:
                    row = connection.execute(
                        "INSERT INTO selection_ledger "
                        "(raindrop_id, selection_day, recording_method, "
                        "first_observed_at) VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (raindrop_id) DO NOTHING RETURNING raindrop_id",
                        (
                            candidate.raindrop_id,
                            day.value,
                            candidate.recording_method.value,
                            candidate.first_observed_at,
                        ),
                    ).fetchone()
                    inserted_count += row is not None
                row = connection.execute(
                    "UPDATE reconciliation_runs SET status = 'complete', "
                    "finished_at = %s, discovered_count = %s, inserted_count = %s "
                    "WHERE run_id = %s AND status = 'running' RETURNING run_id",
                    (finished_at, len(candidates), inserted_count, run_id),
                ).fetchone()
                if row is None:
                    raise LedgerDependencyError(
                        f"Reconciliation run {run_id} is not running"
                    )
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not complete reconciliation") from exc
        return inserted_count

    def finish_reconciliation(
        self,
        run_id: int,
        status: RunStatus,
        finished_at: datetime,
        discovered_count: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Persist an incomplete or failed terminal outcome."""
        if status not in (RunStatus.INCOMPLETE, RunStatus.FAILED):
            raise ValueError("unsuccessful reconciliation requires terminal failure")
        try:
            with self.connection_factory() as connection:
                row = connection.execute(
                    "UPDATE reconciliation_runs SET status = %s, finished_at = %s, "
                    "discovered_count = %s, error_code = %s, error_message = %s "
                    "WHERE run_id = %s AND status = 'running' RETURNING run_id",
                    (
                        status.value,
                        finished_at,
                        discovered_count,
                        error_code,
                        error_message,
                        run_id,
                    ),
                ).fetchone()
                if row is None:
                    raise LedgerDependencyError(
                        f"Reconciliation run {run_id} is not running"
                    )
        except (psycopg.Error, PoolTimeout) as exc:
            raise LedgerDependencyError("Could not finish reconciliation") from exc
