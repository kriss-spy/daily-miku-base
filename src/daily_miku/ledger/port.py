"""Internal Selection Ledger contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain import SelectionDay, SlotCandidate


class LedgerDependencyError(RuntimeError):
    """The durable ledger could not complete an operation."""


class Ledger(Protocol):
    """Store candidate identities and resolve them by Selection Day."""

    def record_candidate(self, day: SelectionDay, candidate: SlotCandidate) -> bool:
        """Record an unseen candidate and report whether it was inserted."""
        ...

    def candidates_for(self, day: SelectionDay) -> tuple[SlotCandidate, ...]:
        """Return candidates in deterministic identity order."""
        ...


class RunStatus(StrEnum):
    """Durable reconciliation run states."""

    RUNNING = "running"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ReconciliationLedger(Ledger, Protocol):
    """Transactional write surface used only by the Reconciler."""

    def start_reconciliation(self, started_at: datetime) -> int:
        """Create a running reconciliation record."""
        ...

    def complete_reconciliation(
        self,
        run_id: int,
        day: SelectionDay,
        candidates: tuple[SlotCandidate, ...],
        finished_at: datetime,
    ) -> int:
        """Atomically insert candidates and mark the run complete."""
        ...

    def finish_reconciliation(
        self,
        run_id: int,
        status: RunStatus,
        finished_at: datetime,
        discovered_count: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Record an incomplete or failed terminal outcome."""
        ...
