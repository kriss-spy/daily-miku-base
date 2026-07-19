"""In-memory Selection Ledger adapter."""

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock

from ..domain import RecordingMethod, SelectionDay, SlotCandidate
from .port import (
    CandidateNotFound,
    CorrectionRecord,
    CorrectionUnchanged,
    RunStatus,
)


@dataclass(frozen=True)
class MemoryReconciliationRun:
    """Observable durable-run equivalent used by tests."""

    run_id: int
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    discovered_count: int = 0
    inserted_count: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class InMemoryLedger:
    """Insert-only fake with the same behavior as the durable adapter."""

    _records: dict[int, tuple[SelectionDay, SlotCandidate]] = field(
        default_factory=dict
    )
    read_count: int = 0
    write_count: int = 0
    runs: list[MemoryReconciliationRun] = field(default_factory=list)
    corrections: list[CorrectionRecord] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record_candidate(self, day: SelectionDay, candidate: SlotCandidate) -> bool:
        """Record a candidate once, preserving its original Selection Day."""
        self.write_count += 1
        if candidate.raindrop_id in self._records:
            return False
        self._records[candidate.raindrop_id] = (day, candidate)
        return True

    def candidates_for(self, day: SelectionDay) -> tuple[SlotCandidate, ...]:
        """Return candidates for a date in ascending Raindrop ID order."""
        self.read_count += 1
        candidates = (
            candidate
            for recorded_day, candidate in self._records.values()
            if recorded_day == day
        )
        return tuple(sorted(candidates, key=lambda item: item.raindrop_id))

    def correct_candidate(
        self,
        raindrop_id: int,
        new_day: SelectionDay,
        reason: str,
        operator: str,
        corrected_at: datetime,
    ) -> CorrectionRecord:
        """Atomically move one candidate and retain its audit history."""
        with self._lock:
            existing = self._records.get(raindrop_id)
            if existing is None:
                raise CandidateNotFound(f"Raindrop {raindrop_id} is not recorded")
            former_day, candidate = existing
            if former_day == new_day:
                raise CorrectionUnchanged(
                    f"Raindrop {raindrop_id} is already assigned to {new_day.value}"
                )
            correction = CorrectionRecord(
                raindrop_id,
                former_day,
                new_day,
                candidate.recording_method,
                reason,
                operator,
                corrected_at,
            )
            self._records[raindrop_id] = (
                new_day,
                SlotCandidate(
                    raindrop_id,
                    RecordingMethod.MANUAL,
                    candidate.first_observed_at,
                ),
            )
            self.corrections.append(correction)
            self.write_count += 1
            return correction

    def start_reconciliation(self, started_at: datetime) -> int:
        """Create a running reconciliation record."""
        with self._lock:
            run_id = len(self.runs) + 1
            self.runs.append(
                MemoryReconciliationRun(run_id, RunStatus.RUNNING, started_at)
            )
            return run_id

    def complete_reconciliation(
        self,
        run_id: int,
        day: SelectionDay,
        candidates: tuple[SlotCandidate, ...],
        finished_at: datetime,
    ) -> int:
        """Atomically record unseen candidates and a successful run."""
        with self._lock:
            run = self._running_run(run_id)
            inserted_count = 0
            for candidate in candidates:
                if candidate.raindrop_id not in self._records:
                    self._records[candidate.raindrop_id] = (day, candidate)
                    inserted_count += 1
            self.write_count += len(candidates)
            self.runs[run_id - 1] = MemoryReconciliationRun(
                run_id,
                RunStatus.COMPLETE,
                run.started_at,
                finished_at,
                len(candidates),
                inserted_count,
            )
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
        """Record an unsuccessful terminal run."""
        if status not in (RunStatus.INCOMPLETE, RunStatus.FAILED):
            raise ValueError("unsuccessful reconciliation requires terminal failure")
        with self._lock:
            run = self._running_run(run_id)
            self.runs[run_id - 1] = MemoryReconciliationRun(
                run_id,
                status,
                run.started_at,
                finished_at,
                discovered_count,
                error_code=error_code,
                error_message=error_message,
            )

    def _running_run(self, run_id: int) -> MemoryReconciliationRun:
        if run_id <= 0 or run_id > len(self.runs):
            raise RuntimeError(f"Unknown reconciliation run {run_id}")
        run = self.runs[run_id - 1]
        if run.status is not RunStatus.RUNNING:
            raise RuntimeError(f"Reconciliation run {run_id} is already finished")
        return run
