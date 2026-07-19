"""Internal Selection Ledger contract."""

from typing import Protocol

from ..domain import SelectionDay, SlotCandidate


class Ledger(Protocol):
    """Store candidate identities and resolve them by Selection Day."""

    def record_candidate(self, day: SelectionDay, candidate: SlotCandidate) -> bool:
        """Record an unseen candidate and report whether it was inserted."""
        ...

    def candidates_for(self, day: SelectionDay) -> tuple[SlotCandidate, ...]:
        """Return candidates in deterministic identity order."""
        ...
