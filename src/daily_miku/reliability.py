"""In-process reliability policies shared by HTTP delivery."""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from time import monotonic
from typing import Callable


@dataclass
class RateLimiter:
    """Bound requests per route class and client within a rolling minute."""

    public_limit: int = 120
    internal_limit: int = 20
    now: Callable[[], float] = monotonic
    _requests: dict[tuple[str, str], deque[float]] = field(
        default_factory=lambda: defaultdict(deque), repr=False
    )

    def retry_after(self, client: str, route_class: str) -> int | None:
        limit = self.internal_limit if route_class == "internal" else self.public_limit
        key = (client, route_class)
        current = self.now()
        requests = self._requests[key]
        while requests and current - requests[0] >= 60:
            requests.popleft()
        if len(requests) >= limit:
            return max(1, int(60 - (current - requests[0])))
        requests.append(current)
        return None
