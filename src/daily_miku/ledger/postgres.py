"""Postgres Selection Ledger adapter."""

from dataclasses import dataclass

from ..domain import RecordingMethod, SelectionDay, SlotCandidate
from .database import ConnectionFactory, postgres_connections


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
