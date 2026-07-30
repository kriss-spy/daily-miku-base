"""Daily Slot states derived solely from candidate cardinality."""

from enum import StrEnum


class SlotState(StrEnum):
    """The three valid Daily Slot states."""

    EMPTY = "empty"
    SELECTED = "selected"
    CONFLICT = "conflict"
