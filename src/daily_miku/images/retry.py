"""Bounded retry policy for transient image dependency operations."""

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Retry transient operations at most three times with bounded jitter."""

    max_attempts: int = 3
    base_delay: float = 0.25
    maximum_delay: float = 2.0
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    jitter: Callable[[], float] = field(default=random.random, repr=False)

    def __post_init__(self) -> None:
        """Reject policies that exceed the contract's three-attempt ceiling."""
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("max_attempts must be between one and three")
        if self.base_delay < 0 or self.maximum_delay < 0:
            raise ValueError("retry delays must not be negative")

    def run(
        self,
        operation: Callable[[], T],
        is_transient: Callable[[Exception], bool],
    ) -> T:
        """Return an operation result or re-raise its final/non-transient error."""
        for attempt in range(self.max_attempts):
            try:
                return operation()
            except Exception as exc:
                if attempt + 1 >= self.max_attempts or not is_transient(exc):
                    raise
                retry_after = getattr(exc, "retry_after", None)
                if isinstance(retry_after, (int, float)):
                    delay = min(self.maximum_delay, max(0.0, float(retry_after)))
                else:
                    ceiling = min(self.maximum_delay, self.base_delay * (2**attempt))
                    jitter = min(1.0, max(0.0, self.jitter()))
                    delay = ceiling * jitter
                self.sleep(delay)
        raise AssertionError("retry loop exhausted without returning or raising")
