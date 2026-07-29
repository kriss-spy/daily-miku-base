"""Raindrop.io API client for fetching daily miku bookmarks."""

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from dotenv import load_dotenv

from .content_source import PAGE_SIZE, RaindropContentSource
from .selection_initialize import (
    GENERIC_SELECTION_TAG,
    SelectionInitializationDependencyError,
    SelectionTagItem,
)

load_dotenv()

logger = logging.getLogger("daily_miku")

RAINDROP_TOKEN = os.getenv("RAINDROP_TOKEN")
RAINDROP_TAG = os.getenv("RAINDROP_TAG", "daily-miku")
RAINDROP_CACHE_TTL = int(os.getenv("RAINDROP_CACHE_TTL", "300"))  # 5 minutes default
BASE_URL = "https://api.raindrop.io/rest/v1"

# Timezone: UTC+8 for Asia
TIMEZONE_OFFSET = timedelta(hours=8)
LOCAL_TZ = timezone(TIMEZONE_OFFSET)


class SimpleCache:
    """Simple in-memory TTL cache."""

    def __init__(self, ttl: int = 300):
        """Initialize cache with TTL in seconds."""
        self.ttl = ttl
        self.cache: dict = {}
        self.timestamps: dict = {}

    def get(self, key: str) -> Optional[list[dict]]:
        """Get value from cache if not expired."""
        if key not in self.cache:
            return None

        elapsed = time.time() - self.timestamps[key]
        if elapsed > self.ttl:
            del self.cache[key]
            del self.timestamps[key]
            return None

        return self.cache[key]

    def set(self, key: str, value: list[dict]) -> None:
        """Set value in cache with current timestamp."""
        self.cache[key] = value
        self.timestamps[key] = time.time()

    def clear(self) -> None:
        """Clear all cached values."""
        self.cache.clear()
        self.timestamps.clear()


class RaindropClient:
    """Client for interacting with Raindrop.io API."""

    def __init__(
        self,
        token: Optional[str] = None,
        tag: Optional[str] = None,
        cache_ttl: Optional[int] = None,
    ):
        self.token = token or RAINDROP_TOKEN
        self.tag = tag or RAINDROP_TAG
        self.cache_ttl = cache_ttl or RAINDROP_CACHE_TTL

        if not self.token:
            raise ValueError("RAINDROP_TOKEN environment variable is required")

        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.cache = SimpleCache(ttl=self.cache_ttl)

    def test_connection(self) -> bool:
        """Test if the API token is valid."""
        try:
            response = requests.get(
                f"{BASE_URL}/raindrops/0",
                headers=self.headers,
                params={"perpage": 1},
                timeout=10,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Connection test failed: {e}")
            return False

    def fetch_raindrops(
        self,
        tag: Optional[str] = None,
        perpage: int = 50,
        page: int = 0,
        sort: str = "-lastUpdate",
    ) -> list[dict]:
        """
        Fetch raindrops with specified tag.

        Args:
            tag: Tag to filter by (default: self.tag)
            perpage: Results per page (max 50)
            page: Page number (0-indexed)
            sort: Sort order ("-lastUpdate" for most recently updated first)

        Returns:
            List of raindrop items
        """
        search_tag = tag or self.tag

        # Create cache key based on parameters
        cache_key = f"raindrops:{search_tag}:{perpage}:{page}:{sort}"

        # Check cache first
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for {cache_key}")
            return cached

        logger.debug(f"Cache miss for {cache_key}, fetching from API")

        params = {
            "search": f"#{search_tag}",
            "perpage": perpage,
            "page": page,
            "sort": sort,
        }

        try:
            response = requests.get(
                f"{BASE_URL}/raindrops/0",
                headers=self.headers,
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])

            logger.info(f"Fetched {len(items)} raindrops with tag '{search_tag}'")

            # Cache the result
            self.cache.set(cache_key, items)

            return items
        except requests.RequestException as e:
            logger.error(f"Failed to fetch raindrops: {e}")
            return []

    def get_by_date(self, date: str) -> Optional[dict]:
        """
        Get daily miku for a specific date based on when it was saved (in UTC+8 timezone).

        Args:
            date: Date string in YYYY-MM-DD format (UTC+8) - when the raindrop was saved

        Returns:
            Raindrop item dict or None if not found
        """
        try:
            target_date = datetime.fromisoformat(date).date()
        except ValueError:
            print(f"Invalid date format: {date}. Use YYYY-MM-DD")
            return None

        # Fetch recent raindrops (could optimize with date-based search if needed)
        items = self.fetch_raindrops(perpage=50)

        for item in items:
            lastUpdate_str = item.get("lastUpdate", "")
            if lastUpdate_str:
                # Parse ISO 8601 timestamp and convert UTC to UTC+8
                utc_time = datetime.fromisoformat(lastUpdate_str.replace("Z", "+00:00"))
                local_time = utc_time.astimezone(LOCAL_TZ)
                saved_date = local_time.date()

                if saved_date == target_date:
                    return item

        return None

    def get_today(self) -> Optional[dict]:
        """Get today's daily miku based on when it was saved (in UTC+8 timezone)."""
        today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
        return self.get_by_date(today)

    def format_response(self, item: dict, date: Optional[str] = None) -> dict:
        """
        Format raindrop item into standardized response.

        Args:
            item: Raw raindrop item from API
            date: Optional date string (YYYY-MM-DD in UTC+8)

        Returns:
            Formatted response dict
        """
        if not item:
            return {}

        # Extract date from lastUpdate timestamp if not provided (convert UTC to UTC+8)
        if not date and item.get("lastUpdate"):
            utc_time = datetime.fromisoformat(item["lastUpdate"].replace("Z", "+00:00"))
            local_time = utc_time.astimezone(LOCAL_TZ)
            date = local_time.strftime("%Y-%m-%d")

        return {
            "date": date,
            "imageUrl": f"https://dailymiku.dev/image/{date}" if date else None,
            "coverUrl": item.get("cover", ""),  # Original Raindrop CDN URL
            "sourceUrl": item.get("link", ""),
            "title": item.get("title", ""),
            "description": item.get("excerpt", ""),
            "note": item.get("note", ""),
            "tags": item.get("tags", []),
            "domain": item.get("domain", ""),
            "raindropId": item.get("_id"),
            "timestamp": item.get("created", ""),
        }

    def clear_cache(self) -> None:
        """Clear the cache."""
        self.cache.clear()


class RaindropSelectionTagStore:
    """Raindrop adapter for complete exact-tag scans and single-item updates."""

    def __init__(
        self,
        token: str,
        *,
        get: Callable[..., Any] = requests.get,
        put: Callable[..., Any] = requests.put,
        timeout: float = 10.0,
    ) -> None:
        """Configure authenticated HTTP operations without retaining tag state."""
        self._headers = {"Authorization": f"Bearer {token}"}
        self._get = get
        self._put = put
        self._timeout = timeout

    def scan_generic(self) -> tuple[SelectionTagItem, ...]:
        """Fetch every bookmark page and retain selection-tag matches locally."""
        results: list[SelectionTagItem] = []
        discovered_ids: set[int] = set()
        expected_count: int | None = None
        raw_count = 0
        page = 0
        try:
            while True:
                response = self._get(
                    f"{BASE_URL}/raindrops/0",
                    headers=self._headers,
                    params={
                        "perpage": PAGE_SIZE,
                        "page": page,
                    },
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
                raw_items, count = self._page(payload)
                if expected_count is None:
                    expected_count = count
                elif count != expected_count:
                    raise ValueError("tagged set changed during pagination")
                raw_count += len(raw_items)
                for raw in raw_items:
                    item = self._item(raw)
                    if item.raindrop_id in discovered_ids:
                        raise ValueError("pagination returned a repeated identity")
                    discovered_ids.add(item.raindrop_id)
                    if any(
                        tag == GENERIC_SELECTION_TAG
                        or tag.startswith(f"{GENERIC_SELECTION_TAG}-")
                        for tag in item.tags
                    ):
                        results.append(item)
                if len(raw_items) < PAGE_SIZE:
                    if raw_count != expected_count:
                        raise ValueError("tagged-set count mismatch")
                    return tuple(results)
                page += 1
                if page > (expected_count // PAGE_SIZE) + 1:
                    raise ValueError("pagination exceeded expected count")
        except (requests.RequestException, TypeError, ValueError, KeyError) as exc:
            raise SelectionInitializationDependencyError(
                "Raindrop could not provide a complete selection-tag snapshot."
            ) from exc

    def get(self, raindrop_id: int) -> SelectionTagItem:
        """Fetch current mutation evidence for one Raindrop."""
        try:
            response = self._get(
                f"{BASE_URL}/raindrop/{raindrop_id}",
                headers=self._headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            raw = payload.get("item") if isinstance(payload, dict) else None
            if not isinstance(raw, dict):
                raise ValueError("response does not contain an item")
            item = self._item(raw)
            if item.raindrop_id != raindrop_id:
                raise ValueError("response identity does not match request")
            return item
        except (requests.RequestException, TypeError, ValueError, KeyError) as exc:
            raise SelectionInitializationDependencyError(
                "Raindrop could not refetch initialization evidence."
            ) from exc

    def update_tags(self, raindrop_id: int, tags: tuple[str, ...]) -> None:
        """Use Raindrop's supported single-raindrop PUT replacement semantics."""
        try:
            response = self._put(
                f"{BASE_URL}/raindrop/{raindrop_id}",
                headers=self._headers,
                json={"tags": list(tags)},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("result") is not True:
                raise ValueError("response does not confirm the update")
        except (requests.RequestException, TypeError, ValueError) as exc:
            raise SelectionInitializationDependencyError(
                "Raindrop could not update selection tags."
            ) from exc

    @staticmethod
    def _page(payload: Any) -> tuple[list[dict[str, Any]], int]:
        if not isinstance(payload, dict):
            raise ValueError("response is not an object")
        raw_items = payload.get("items")
        count = payload.get("count")
        if (
            not isinstance(raw_items, list)
            or not isinstance(count, int)
            or count < 0
            or len(raw_items) > PAGE_SIZE
            or not all(isinstance(item, dict) for item in raw_items)
        ):
            raise ValueError("response has invalid pagination fields")
        return raw_items, count

    @staticmethod
    def _item(raw: dict[str, Any]) -> SelectionTagItem:
        if "tags" not in raw:
            raise ValueError("response omits tags")
        parsed = RaindropContentSource._parse_item(raw)
        if parsed.last_update is None:
            raise ValueError("response omits lastUpdate")
        return SelectionTagItem(
            parsed.raindrop_id,
            parsed.last_update,
            parsed.tags,
            parsed.source_url,
            parsed.cover_identity,
        )


def get_client() -> RaindropClient:
    """Get a configured RaindropClient instance."""
    return RaindropClient()
