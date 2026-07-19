"""In-memory Selection Ledger adapter."""

from dataclasses import dataclass, field

from ..domain import SelectionDay, SlotCandidate


@dataclass
class InMemoryLedger:
    """Insert-only fake with the same behavior as the durable adapter."""

    _records: dict[int, tuple[SelectionDay, SlotCandidate]] = field(
        default_factory=dict
    )
    read_count: int = 0
    write_count: int = 0

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
