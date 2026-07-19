"""Controllable time source used by all v2 date decisions."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Provide the current timezone-aware instant."""

    def now(self) -> datetime:
        """Return the current instant."""
        ...


class SystemClock:
    """Clock backed by the system UTC time."""

    def now(self) -> datetime:
        """Return the current UTC instant."""
        return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FixedClock:
    """Clock fixed at one instant for deterministic behavior."""

    instant: datetime

    def __post_init__(self) -> None:
        """Reject ambiguous naive datetimes."""
        if self.instant.tzinfo is None or self.instant.utcoffset() is None:
            raise ValueError("FixedClock requires a timezone-aware instant")

    def now(self) -> datetime:
        """Return the configured instant."""
        return self.instant
