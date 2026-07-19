"""Raindrop-authoritative tagged content source adapters."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

import requests

BASE_URL = "https://api.raindrop.io/rest/v1"
PAGE_SIZE = 50


class ScanStatus(StrEnum):
    """Whether a tagged-set traversal produced a complete snapshot."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True)
class TaggedItem:
    """Stable identity discovered in the current tagged set."""

    raindrop_id: int

    def __post_init__(self) -> None:
        """Require a valid Raindrop identity."""
        if self.raindrop_id <= 0:
            raise ValueError("raindrop_id must be positive")


@dataclass(frozen=True)
class TaggedScan:
    """One complete, incomplete, or failed tagged-set traversal."""

    status: ScanStatus
    items: tuple[TaggedItem, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Keep successful and unsuccessful scan representations distinct."""
        if self.status is ScanStatus.COMPLETE and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("complete scans cannot contain an error")
        if self.status is not ScanStatus.COMPLETE and not self.error_code:
            raise ValueError("unsuccessful scans require an error code")


class ContentSource(Protocol):
    """Return the complete current set matching the configured tag."""

    def scan_tagged(self) -> TaggedScan:
        """Traverse every documented Raindrop page."""
        ...


@dataclass
class InMemoryContentSource:
    """Configurable content-source fake for isolated tests."""

    items: tuple[TaggedItem, ...] = ()
    status: ScanStatus = ScanStatus.COMPLETE
    error_code: str = "injected_scan_failure"
    scan_count: int = 0

    def scan_tagged(self) -> TaggedScan:
        """Return the configured scan outcome."""
        self.scan_count += 1
        if self.status is ScanStatus.COMPLETE:
            return TaggedScan(self.status, self.items)
        return TaggedScan(
            self.status,
            self.items,
            self.error_code,
            "The tagged set could not be scanned completely.",
        )


class HTTPResponse(Protocol):
    """Response behavior required by the Raindrop adapter."""

    def raise_for_status(self) -> None:
        """Raise for an unsuccessful HTTP status."""
        ...

    def json(self) -> Any:
        """Decode the response body."""
        ...


HTTPGet = Callable[..., HTTPResponse]


@dataclass
class RaindropContentSource:
    """Complete paginated Raindrop tagged-set adapter."""

    token: str
    tag: str
    get: HTTPGet = field(default=requests.get, repr=False)
    timeout: float = 10.0

    def scan_tagged(self) -> TaggedScan:
        """Fetch every page without relying on last-update ordering."""
        discovered: dict[int, TaggedItem] = {}
        expected_count: int | None = None
        page = 0

        while True:
            try:
                response = self.get(
                    f"{BASE_URL}/raindrops/0",
                    headers={"Authorization": f"Bearer {self.token}"},
                    params={
                        "search": f"#{self.tag}",
                        "perpage": PAGE_SIZE,
                        "page": page,
                    },
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                items, count = self._validate_page(payload)
            except (requests.RequestException, TypeError, ValueError) as exc:
                return self._failed_scan(discovered, exc)

            if expected_count is None:
                expected_count = count
            elif count != expected_count:
                return TaggedScan(
                    ScanStatus.INCOMPLETE,
                    tuple(discovered.values()),
                    "tagged_set_changed",
                    "The tagged set changed during pagination.",
                )

            for item in items:
                if item.raindrop_id in discovered:
                    return TaggedScan(
                        ScanStatus.INCOMPLETE,
                        tuple(discovered.values()),
                        "duplicate_page_identity",
                        "Pagination returned a repeated Raindrop identity.",
                    )
                discovered[item.raindrop_id] = item

            if len(items) < PAGE_SIZE:
                if len(discovered) != expected_count:
                    return TaggedScan(
                        ScanStatus.INCOMPLETE,
                        tuple(discovered.values()),
                        "count_mismatch",
                        "The tagged-set count did not match the fetched pages.",
                    )
                return TaggedScan(ScanStatus.COMPLETE, tuple(discovered.values()))

            page += 1
            maximum_pages = (expected_count // PAGE_SIZE) + 1
            if page > maximum_pages:
                return TaggedScan(
                    ScanStatus.INCOMPLETE,
                    tuple(discovered.values()),
                    "pagination_limit",
                    "The tagged-set scan exceeded its expected page count.",
                )

    @staticmethod
    def _validate_page(payload: Any) -> tuple[tuple[TaggedItem, ...], int]:
        if not isinstance(payload, dict):
            raise ValueError("response is not an object")
        raw_items = payload.get("items")
        count = payload.get("count")
        if not isinstance(raw_items, list) or not isinstance(count, int) or count < 0:
            raise ValueError("response has invalid pagination fields")

        items = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict) or not isinstance(
                raw_item.get("_id"), int
            ):
                raise ValueError("response contains an invalid item")
            items.append(TaggedItem(raw_item["_id"]))
        if len(items) > PAGE_SIZE:
            raise ValueError("response exceeds the requested page size")
        return tuple(items), count

    @staticmethod
    def _failed_scan(discovered: dict[int, TaggedItem], exc: Exception) -> TaggedScan:
        status = ScanStatus.INCOMPLETE if discovered else ScanStatus.FAILED
        code = (
            "raindrop_request_failed"
            if isinstance(exc, requests.RequestException)
            else "raindrop_response_invalid"
        )
        return TaggedScan(
            status,
            tuple(discovered.values()),
            code,
            "Raindrop could not provide a complete tagged set.",
        )
