"""Audited manual correction of one recorded Selection Day."""

from dataclasses import dataclass
from datetime import date, timezone

from .domain import Calendar, Clock
from .ledger.port import CorrectionLedger, CorrectionRecord


@dataclass(frozen=True)
class SelectionCorrector:
    """Validate and apply the controlled exception to insert-only dates."""

    ledger: CorrectionLedger
    calendar: Calendar
    clock: Clock
    operator: str

    def correct(
        self, raindrop_id: int, new_date: date, reason: str
    ) -> CorrectionRecord:
        """Correct one identity after validating operator-controlled evidence."""
        if raindrop_id <= 0:
            raise ValueError("Raindrop ID must be positive.")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("Correction reason must not be blank.")
        normalized_operator = self.operator.strip()
        if not normalized_operator:
            raise ValueError("Correction operator must not be blank.")
        day = self.calendar.require_not_future(new_date, self.clock)
        corrected_at = self.clock.now().astimezone(timezone.utc)
        return self.ledger.correct_candidate(
            raindrop_id,
            day,
            normalized_reason,
            normalized_operator,
            corrected_at,
        )
