"""Daily Slot states derived solely from candidate cardinality."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .calendar import SelectionDay


class SlotState(StrEnum):
    """The three valid Daily Slot states."""

    EMPTY = "empty"
    SELECTED = "selected"
    CONFLICT = "conflict"


class RecordingMethod(StrEnum):
    """How a candidate's Selection Day entered the ledger."""

    LEGACY = "legacy"
    OBSERVED = "observed"
    MANUAL = "manual"


@dataclass(frozen=True)
class SlotCandidate:
    """Minimal immutable ledger identity needed to derive a Slot."""

    raindrop_id: int
    recording_method: RecordingMethod
    first_observed_at: datetime

    def __post_init__(self) -> None:
        """Require a positive identity and an unambiguous observation instant."""
        if self.raindrop_id <= 0:
            raise ValueError("raindrop_id must be positive")
        if (
            self.first_observed_at.tzinfo is None
            or self.first_observed_at.utcoffset() is None
        ):
            raise ValueError("first_observed_at must be timezone-aware")


@dataclass(frozen=True)
class DailySlot:
    """All candidates assigned to one Selection Day."""

    day: SelectionDay
    candidates: tuple[SlotCandidate, ...] = ()

    @property
    def state(self) -> SlotState:
        """Derive state without selecting a winner from a conflict."""
        count = len(self.candidates)
        if count == 0:
            return SlotState.EMPTY
        if count == 1:
            return SlotState.SELECTED
        return SlotState.CONFLICT
