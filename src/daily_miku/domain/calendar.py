"""Selection Day and calendar-timezone rules."""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .clock import Clock


class FutureSelectionDay(ValueError):
    """Raised when a requested Selection Day has not begun locally."""


@dataclass(frozen=True, order=True)
class SelectionDay:
    """A calendar date interpreted in the configured calendar timezone."""

    value: date


@dataclass(frozen=True)
class Calendar:
    """Convert instants and validate dates in one named timezone."""

    timezone: ZoneInfo

    @classmethod
    def named(cls, timezone_name: str) -> "Calendar":
        """Build a calendar from an IANA timezone name."""
        return cls(ZoneInfo(timezone_name))

    def selection_day(self, instant: datetime) -> SelectionDay:
        """Return the local Selection Day containing an instant."""
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("Selection Day requires a timezone-aware instant")
        return SelectionDay(instant.astimezone(self.timezone).date())

    def today(self, clock: Clock) -> SelectionDay:
        """Return today's Selection Day using a supplied clock."""
        return self.selection_day(clock.now())

    def require_not_future(self, day: date, clock: Clock) -> SelectionDay:
        """Return a Selection Day unless it is after local today."""
        selection_day = SelectionDay(day)
        if selection_day > self.today(clock):
            raise FutureSelectionDay(
                f"Selection Day {day.isoformat()} is in the future"
            )
        return selection_day
