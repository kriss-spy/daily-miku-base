"""Read-only Daily Slot catalog."""

from dataclasses import dataclass
from datetime import date

from .domain import Calendar, Clock, DailySlot
from .ledger.port import Ledger


@dataclass(frozen=True)
class SlotCatalog:
    """Resolve Daily Slots without changing ledger state."""

    ledger: Ledger
    calendar: Calendar
    clock: Clock

    def get_slot(self, day: date) -> DailySlot:
        """Resolve a non-future calendar date to its complete Daily Slot."""
        selection_day = self.calendar.require_not_future(day, self.clock)
        return DailySlot(selection_day, self.ledger.candidates_for(selection_day))
