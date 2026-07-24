"""Internal Selection Ledger contracts."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..domain import RecordingMethod, SelectionDay, SlotCandidate


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

    def candidates_between(
        self, first: SelectionDay, last: SelectionDay
    ) -> tuple[tuple[SelectionDay, SlotCandidate], ...]:
        """Return candidates in Selection Day and identity order, inclusively."""
        ...


class CandidateNotFound(ValueError):
    """The requested Raindrop identity is not recorded in the ledger."""


class CorrectionUnchanged(ValueError):
    """A correction requested the candidate's existing Selection Day."""


@dataclass(frozen=True)
class CorrectionRecord:
    """Immutable facts recorded for one audited Selection Day correction."""

    raindrop_id: int
    former_day: SelectionDay
    new_day: SelectionDay
    former_method: RecordingMethod
    reason: str
    operator: str
    corrected_at: datetime
    new_method: RecordingMethod = RecordingMethod.MANUAL


class CorrectionLedger(Ledger, Protocol):
    """Transactional mutation surface for audited manual corrections."""

    def correct_candidate(
        self,
        raindrop_id: int,
        new_day: SelectionDay,
        reason: str,
        operator: str,
        corrected_at: datetime,
    ) -> CorrectionRecord:
        """Move one candidate and append its before-and-after audit facts."""
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

    def reconciliation_runs(self) -> tuple[object, ...]:
        """Return durable runs newest-first for operational freshness."""
        ...

    def schema_version(self) -> int:
        """Return the latest applied numbered migration."""
        ...


class InitializationLedger(Ledger, Protocol):
    """Read and transactional write surface for one-time initialization."""

    def recorded_raindrop_ids(self, raindrop_ids: Sequence[int]) -> frozenset[int]:
        """Return the requested identities already present in the ledger."""
        ...

    def initialize_candidates(
        self, rows: Sequence[tuple[SelectionDay, SlotCandidate]]
    ) -> int:
        """Atomically insert conflict-safe legacy candidate rows."""
        ...


class OperationalLedger(
    ReconciliationLedger, CorrectionLedger, InitializationLedger, Protocol
):
    """Complete ledger surface required by the application composition root."""
