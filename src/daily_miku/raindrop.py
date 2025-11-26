"""Raindrop.io API client for fetching daily miku bookmarks."""

import os
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

RAINDROP_TOKEN = os.getenv("RAINDROP_TOKEN")
RAINDROP_TAG = os.getenv("RAINDROP_TAG", "daily-miku")
BASE_URL = "https://api.raindrop.io/rest/v1"


class RaindropClient:
    """Client for interacting with Raindrop.io API."""

    def __init__(self, token: Optional[str] = None, tag: Optional[str] = None):
        self.token = token or RAINDROP_TOKEN
        self.tag = tag or RAINDROP_TAG

        if not self.token:
            raise ValueError("RAINDROP_TOKEN environment variable is required")

        self.headers = {"Authorization": f"Bearer {self.token}"}

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
        sort: str = "-created",
    ) -> list[dict]:
        """
        Fetch raindrops with specified tag.

        Args:
            tag: Tag to filter by (default: self.tag)
            perpage: Results per page (max 50)
            page: Page number (0-indexed)
            sort: Sort order ("-created" for newest first)

        Returns:
            List of raindrop items
        """
        search_tag = tag or self.tag
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
            return data.get("items", [])
        except requests.RequestException as e:
            print(f"Failed to fetch raindrops: {e}")
            return []

    def get_by_date(self, date: str) -> Optional[dict]:
        """
        Get daily miku for a specific date.

        Args:
            date: Date string in YYYY-MM-DD format

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
            created_str = item.get("created", "")
            if created_str:
                # Parse ISO 8601 timestamp
                created_date = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                ).date()

                if created_date == target_date:
                    return item

        return None

    def get_today(self) -> Optional[dict]:
        """Get today's daily miku."""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.get_by_date(today)

    def format_response(self, item: dict, date: Optional[str] = None) -> dict:
        """
        Format raindrop item into standardized response.

        Args:
            item: Raw raindrop item from API
            date: Optional date string (YYYY-MM-DD)

        Returns:
            Formatted response dict
        """
        if not item:
            return {}

        # Extract date from created timestamp if not provided
        if not date and item.get("created"):
            date = datetime.fromisoformat(
                item["created"].replace("Z", "+00:00")
            ).strftime("%Y-%m-%d")

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


def get_client() -> RaindropClient:
    """Get a configured RaindropClient instance."""
    return RaindropClient()
