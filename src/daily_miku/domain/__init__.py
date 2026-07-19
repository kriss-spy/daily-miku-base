"""Pure domain types for Daily Miku v2."""

from .calendar import Calendar, FutureSelectionDay, SelectionDay
from .clock import Clock, FixedClock, SystemClock
from .slots import DailySlot, RecordingMethod, SlotCandidate, SlotState

__all__ = [
    "Calendar",
    "Clock",
    "DailySlot",
    "FixedClock",
    "FutureSelectionDay",
    "RecordingMethod",
    "SelectionDay",
    "SlotCandidate",
    "SlotState",
    "SystemClock",
]
