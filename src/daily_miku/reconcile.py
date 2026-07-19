"""Complete tagged-set reconciliation into the Selection Ledger."""

from dataclasses import dataclass
from datetime import timezone
import logging

from .content_source import ContentSource, ScanStatus
from .domain import Calendar, Clock, RecordingMethod, SlotCandidate
from .ledger.port import LedgerDependencyError, ReconciliationLedger, RunStatus

logger = logging.getLogger("daily_miku.v2.reconcile")


class ReconciliationDependencyError(RuntimeError):
    """A durable reconciliation operation could not be recorded safely."""


@dataclass(frozen=True)
class ReconciliationReport:
    """Safe observable result shared by CLI and HTTP delivery."""

    run_id: int
    status: RunStatus
    discovered_count: int
    inserted_count: int
    error_code: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, object]:
        """Serialize the stable operator response document."""
        document: dict[str, object] = {
            "run_id": self.run_id,
            "status": self.status.value,
            "discovered": self.discovered_count,
            "inserted": self.inserted_count,
        }
        if self.error_code is not None:
            document["error"] = {
                "code": self.error_code,
                "message": self.error_message,
                "details": {},
            }
        return document


@dataclass(frozen=True)
class Reconciler:
    """The only routine Selection Ledger write path."""

    ledger: ReconciliationLedger
    content_source: ContentSource
    calendar: Calendar
    clock: Clock

    def reconcile(self) -> ReconciliationReport:
        """Persist one complete observation or a safe unsuccessful run."""
        observed_at = self.clock.now().astimezone(timezone.utc)
        try:
            run_id = self.ledger.start_reconciliation(observed_at)
        except LedgerDependencyError as exc:
            logger.exception("reconciliation_start_failed")
            raise ReconciliationDependencyError(
                "The reconciliation run could not be started."
            ) from exc
        scan = self.content_source.scan_tagged()
        discovered_count = len(scan.items)

        if scan.status is not ScanStatus.COMPLETE:
            status = (
                RunStatus.INCOMPLETE
                if scan.status is ScanStatus.INCOMPLETE
                else RunStatus.FAILED
            )
            error_code = scan.error_code or "tagged_scan_failed"
            error_message = scan.error_message or "The tagged set scan failed."
            self._finish_unsuccessful_run(
                run_id,
                status,
                discovered_count,
                error_code,
                error_message,
            )
            return ReconciliationReport(
                run_id,
                status,
                discovered_count,
                0,
                error_code,
                error_message,
            )

        day = self.calendar.selection_day(observed_at)
        candidates = tuple(
            SlotCandidate(item.raindrop_id, RecordingMethod.OBSERVED, observed_at)
            for item in scan.items
        )
        try:
            inserted_count = self.ledger.complete_reconciliation(
                run_id,
                day,
                candidates,
                self.clock.now().astimezone(timezone.utc),
            )
        except LedgerDependencyError:
            logger.exception("reconciliation_commit_failed")
            self._finish_unsuccessful_run(
                run_id,
                RunStatus.FAILED,
                discovered_count,
                "ledger_write_failed",
                "The Selection Ledger could not record reconciliation.",
            )
            return ReconciliationReport(
                run_id,
                RunStatus.FAILED,
                discovered_count,
                0,
                "ledger_write_failed",
                "The Selection Ledger could not record reconciliation.",
            )

        return ReconciliationReport(
            run_id, RunStatus.COMPLETE, discovered_count, inserted_count
        )

    def _finish_unsuccessful_run(
        self,
        run_id: int,
        status: RunStatus,
        discovered_count: int,
        error_code: str,
        error_message: str,
    ) -> None:
        try:
            self.ledger.finish_reconciliation(
                run_id,
                status,
                self.clock.now().astimezone(timezone.utc),
                discovered_count,
                error_code,
                error_message,
            )
        except LedgerDependencyError as exc:
            logger.exception("reconciliation_finish_failed")
            raise ReconciliationDependencyError(
                "The reconciliation outcome could not be recorded."
            ) from exc
