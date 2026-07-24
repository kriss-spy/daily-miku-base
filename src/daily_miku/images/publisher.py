"""Raindrop cover mutation port used only by controlled ingestion."""

from dataclasses import dataclass, field
from typing import Protocol

import requests

from ..content_source import BASE_URL


class CoverDependencyError(RuntimeError):
    """Raindrop could not accept the controlled cover reference."""

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        timeout: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.timeout = timeout
        self.retry_after = retry_after


@dataclass(frozen=True)
class CoverChange:
    """Reversible Raindrop cover mutation facts."""

    raindrop_id: int
    former_url: str | None
    new_url: str


class CoverPublisher(Protocol):
    """Apply and compensate the external Raindrop cover mutation."""

    def prepare_cover_change(self, raindrop_id: int, blob_url: str) -> CoverChange:
        """Capture the original cover once before any mutation attempt."""
        ...

    def apply_cover(self, change: CoverChange) -> None:
        """Idempotently apply the prepared controlled cover mutation."""
        ...

    def restore_cover(self, change: CoverChange) -> None:
        """Compensate a cover update whose metadata activation failed."""
        ...


@dataclass
class InMemoryCoverPublisher:
    """Observable no-network cover publisher."""

    covers: dict[int, str] = field(default_factory=dict)
    fail: bool = False

    set_count: int = 0
    restore_count: int = 0

    def prepare_cover_change(self, raindrop_id: int, blob_url: str) -> CoverChange:
        """Capture the exact prior fake cover without mutating it."""
        return CoverChange(raindrop_id, self.covers.get(raindrop_id), blob_url)

    def apply_cover(self, change: CoverChange) -> None:
        """Record a prepared cover update or inject a failure."""
        self.set_count += 1
        if self.fail:
            raise CoverDependencyError("Raindrop cover update failed")
        self.covers[change.raindrop_id] = change.new_url

    def restore_cover(self, change: CoverChange) -> None:
        """Restore the exact prior fake cover state."""
        self.restore_count += 1
        if self.fail:
            raise CoverDependencyError("Raindrop cover restore failed")
        if change.former_url is None:
            self.covers.pop(change.raindrop_id, None)
        else:
            self.covers[change.raindrop_id] = change.former_url


@dataclass(frozen=True)
class RaindropCoverPublisher:
    """Authenticated Raindrop cover update adapter."""

    token: str
    timeout: float = 10.0

    def prepare_cover_change(self, raindrop_id: int, blob_url: str) -> CoverChange:
        """Read the former cover once and create immutable compensation facts."""
        try:
            response = requests.get(
                f"{BASE_URL}/raindrop/{raindrop_id}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            item = payload.get("item") if isinstance(payload, dict) else None
            former_url = item.get("cover") if isinstance(item, dict) else None
            if former_url is not None and not isinstance(former_url, str):
                raise ValueError("Raindrop returned an invalid cover")
            return CoverChange(raindrop_id, former_url, blob_url)
        except requests.Timeout as exc:
            raise CoverDependencyError(
                "Raindrop cover update timed out", transient=True, timeout=True
            ) from exc
        except requests.ConnectionError as exc:
            raise CoverDependencyError(
                "Raindrop cover update failed", transient=True
            ) from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            retry_after = _retry_after(exc.response)
            raise CoverDependencyError(
                "Raindrop cover update failed",
                transient=(status is not None and status >= 500)
                or (status == 429 and retry_after is not None),
                retry_after=retry_after,
            ) from exc
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise CoverDependencyError("Raindrop cover update failed") from exc

    def apply_cover(self, change: CoverChange) -> None:
        """Apply a prepared cover change without re-reading its original value."""
        self._put_cover(change.raindrop_id, change.new_url)

    def restore_cover(self, change: CoverChange) -> None:
        """Restore the cover value captured before a failed activation."""
        self._put_cover(change.raindrop_id, change.former_url or "")

    def _put_cover(self, raindrop_id: int, cover_url: str) -> None:
        try:
            response = requests.put(
                f"{BASE_URL}/raindrop/{raindrop_id}",
                headers={"Authorization": f"Bearer {self.token}"},
                json={"cover": cover_url},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise CoverDependencyError(
                "Raindrop cover update timed out", transient=True, timeout=True
            ) from exc
        except requests.ConnectionError as exc:
            raise CoverDependencyError(
                "Raindrop cover update failed", transient=True
            ) from exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            retry_after = _retry_after(exc.response)
            raise CoverDependencyError(
                "Raindrop cover update failed",
                transient=(status is not None and status >= 500)
                or (status == 429 and retry_after is not None),
                retry_after=retry_after,
            ) from exc
        except requests.RequestException as exc:
            raise CoverDependencyError("Raindrop cover update failed") from exc


def _retry_after(response: requests.Response | None) -> float | None:
    """Return a bounded usable Retry-After delta for Raindrop rate limits."""
    if response is None or response.status_code != 429:
        return None
    try:
        value = float(response.headers["Retry-After"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if 0 <= value <= 2.0 else None
