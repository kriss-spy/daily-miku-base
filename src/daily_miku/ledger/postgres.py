"""Postgres Selection Ledger adapter."""

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg_pool import PoolTimeout

from ..domain import RecordingMethod, SelectionDay, SlotCandidate
from .database import ConnectionFactory, postgres_connections
from .port import LedgerDependencyError, RunStatus


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
        with self.connection_factory() as connection:
            rows = connection.execute(
                "SELECT raindrop_id, recording_method, first_observed_at "
                "FROM selection_ledger WHERE selection_day = %s "
                "ORDER BY raindrop_id ASC",
                (day.value,),
            ).fetchall()
        return tuple(
            SlotCandidate(
                raindrop_id=int(row[0]),
                recording_method=RecordingMethod(str(row[1])),
                first_observed_at=row[2],
            )
            for row in rows
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
