"""Raindrop-authoritative tagged content source adapters."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

import requests

BASE_URL = "https://api.raindrop.io/rest/v1"
PAGE_SIZE = 50


class ContentFailure(StrEnum):
    """Stable classes of current-content dependency failure."""

    UPSTREAM = "upstream"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


class ContentDependencyError(RuntimeError):
    """Current Raindrop content could not be read completely."""

    def __init__(
        self, message: str, kind: ContentFailure = ContentFailure.UNAVAILABLE
    ) -> None:
        super().__init__(message)
        self.kind = kind


class ScanStatus(StrEnum):
    """Whether a tagged-set traversal produced a complete snapshot."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True)
class TaggedItem:
    """Current tagged identity and legacy-initialization evidence."""

    raindrop_id: int
    last_update: datetime | None = None
    source_url: str | None = None
    cover_identity: str | None = None
    title: str = "Untitled"
    excerpt: str | None = None
    domain: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Require a valid Raindrop identity."""
        if self.raindrop_id <= 0:
            raise ValueError("raindrop_id must be positive")
        if self.last_update is not None and (
            self.last_update.tzinfo is None or self.last_update.utcoffset() is None
        ):
            raise ValueError("last_update must be timezone-aware")


@dataclass(frozen=True)
class TaggedScan:
    """One complete, incomplete, or failed tagged-set traversal."""

    status: ScanStatus
    items: tuple[TaggedItem, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    failure: ContentFailure | None = None

    def __post_init__(self) -> None:
        """Keep successful and unsuccessful scan representations distinct."""
        if self.status is ScanStatus.COMPLETE and (
            self.error_code is not None
            or self.error_message is not None
            or self.failure is not None
        ):
            raise ValueError("complete scans cannot contain an error")
        if self.status is not ScanStatus.COMPLETE and not self.error_code:
            raise ValueError("unsuccessful scans require an error code")


class ContentSource(Protocol):
    """Return the complete current set matching the configured tag."""

    def scan_tagged(self) -> TaggedScan:
        """Traverse every documented Raindrop page."""
        ...

    def get_items(self, raindrop_ids: tuple[int, ...]) -> tuple[TaggedItem, ...]:
        """Return current metadata for every requested identity."""
        ...


@dataclass
class InMemoryContentSource:
    """Configurable content-source fake for isolated tests."""

    items: tuple[TaggedItem, ...] = ()
    status: ScanStatus = ScanStatus.COMPLETE
    error_code: str = "injected_scan_failure"
    scan_count: int = 0
    lookup_count: int = 0
    lookup_failure: ContentFailure | None = None

    def scan_tagged(self) -> TaggedScan:
        """Return the configured scan outcome."""
        self.scan_count += 1
        if self.status is ScanStatus.COMPLETE and self.lookup_failure is None:
            return TaggedScan(self.status, self.items)
        status = self.status
        if status is ScanStatus.COMPLETE:
            status = ScanStatus.FAILED
        return TaggedScan(
            status,
            self.items,
            self.error_code,
            "The tagged set could not be scanned completely.",
            self.lookup_failure,
        )

    def get_items(self, raindrop_ids: tuple[int, ...]) -> tuple[TaggedItem, ...]:
        """Resolve current content from the configured fake snapshot."""
        self.lookup_count += 1
        if self.lookup_failure is not None:
            raise ContentDependencyError(
                "Raindrop content is unavailable", self.lookup_failure
            )
        by_id = {item.raindrop_id: item for item in self.items}
        try:
            return tuple(by_id[raindrop_id] for raindrop_id in raindrop_ids)
        except KeyError as exc:
            raise ContentDependencyError("Raindrop content is unavailable") from exc


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
        """Fetch all bookmarks and retain every selection-prefix tag locally."""
        discovered: dict[int, TaggedItem] = {}
        expected_count: int | None = None
        page = 0

        while True:
            try:
                response = self.get(
                    f"{BASE_URL}/raindrops/0",
                    headers={"Authorization": f"Bearer {self.token}"},
                    params={
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
                selected = tuple(
                    item
                    for item in discovered.values()
                    if any(
                        tag == self.tag or tag.startswith("daily-miku-")
                        for tag in item.tags
                    )
                )
                return TaggedScan(ScanStatus.COMPLETE, selected)

            page += 1
            maximum_pages = (expected_count // PAGE_SIZE) + 1
            if page > maximum_pages:
                return TaggedScan(
                    ScanStatus.INCOMPLETE,
                    tuple(discovered.values()),
                    "pagination_limit",
                    "The tagged-set scan exceeded its expected page count.",
                )

    def get_items(self, raindrop_ids: tuple[int, ...]) -> tuple[TaggedItem, ...]:
        """Fetch Raindrop-authoritative current metadata by durable identity."""
        items: list[TaggedItem] = []
        for raindrop_id in raindrop_ids:
            try:
                response = self.get(
                    f"{BASE_URL}/raindrop/{raindrop_id}",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                raw_item = payload.get("item") if isinstance(payload, dict) else None
                if not isinstance(raw_item, dict):
                    raise ValueError("response does not contain an item")
                item = self._parse_item(raw_item, require_content=True)
                if item.raindrop_id != raindrop_id:
                    raise ValueError("response identity does not match request")
                items.append(item)
            except requests.Timeout as exc:
                raise ContentDependencyError(
                    "Raindrop content lookup timed out.", ContentFailure.TIMEOUT
                ) from exc
            except requests.ConnectionError as exc:
                raise ContentDependencyError(
                    "Raindrop content is unavailable.", ContentFailure.UNAVAILABLE
                ) from exc
            except (requests.RequestException, TypeError, ValueError) as exc:
                raise ContentDependencyError(
                    "Raindrop could not provide current content.",
                    ContentFailure.UPSTREAM,
                ) from exc
        return tuple(items)

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
            if (
                not isinstance(raw_item, dict)
                or not isinstance(raw_item.get("_id"), int)
                or "tags" not in raw_item
            ):
                raise ValueError("response contains an invalid item")
            items.append(RaindropContentSource._parse_item(raw_item))
        if len(items) > PAGE_SIZE:
            raise ValueError("response exceeds the requested page size")
        return tuple(items), count

    @staticmethod
    def _parse_item(
        raw_item: dict[str, Any], *, require_content: bool = False
    ) -> TaggedItem:
        """Validate and map fields used by migration tooling and Slot reads."""
        if not isinstance(raw_item.get("_id"), int):
            raise ValueError("response contains an invalid item")
        last_update = raw_item.get("lastUpdate")
        source_url = raw_item.get("link")
        cover_identity = raw_item.get("cover")
        title = raw_item.get("title", "Untitled")
        excerpt = raw_item.get("excerpt")
        domain = raw_item.get("domain")
        tags = raw_item.get("tags", [])
        if require_content and ("title" not in raw_item or "tags" not in raw_item):
            raise ValueError("response omits required content fields")
        if last_update is not None and not isinstance(last_update, str):
            raise ValueError("response contains an invalid lastUpdate")
        optional_strings = (source_url, cover_identity, excerpt, domain)
        if any(
            value is not None and not isinstance(value, str)
            for value in optional_strings
        ):
            raise ValueError("response contains invalid content fields")
        if (
            not isinstance(title, str)
            or not isinstance(tags, list)
            or not all(isinstance(tag, str) for tag in tags)
        ):
            raise ValueError("response contains invalid content fields")
        parsed_last_update = (
            datetime.fromisoformat(last_update.replace("Z", "+00:00"))
            if last_update is not None
            else None
        )
        return TaggedItem(
            raw_item["_id"],
            parsed_last_update,
            source_url,
            cover_identity,
            title,
            excerpt,
            domain,
            tuple(tags),
        )

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
            (
                ContentFailure.TIMEOUT
                if isinstance(exc, requests.Timeout)
                else ContentFailure.UNAVAILABLE
                if isinstance(exc, requests.ConnectionError)
                else ContentFailure.UPSTREAM
            ),
        )
