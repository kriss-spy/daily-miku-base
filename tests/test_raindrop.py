"""Tests for Raindrop.io API client."""

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests_mock

from daily_miku.raindrop import RaindropClient, get_client, SimpleCache


@pytest.fixture
def mock_env():
    """Mock environment variables."""
    with patch.dict(os.environ, {"RAINDROP_TOKEN": "test_token_123"}, clear=True):
        yield


@pytest.fixture
def sample_raindrop():
    """Sample raindrop item for testing."""
    return {
        "_id": 123456,
        "title": "Hatsune Miku Daily #42",
        "excerpt": "Beautiful Miku artwork",
        "note": "Test note",
        "cover": "https://cdn.raindrop.io/test/image.jpg",
        "link": "https://twitter.com/example/status/123",
        "domain": "twitter.com",
        "tags": ["daily-miku", "vocaloid"],
        "created": "2025-01-15T12:00:00.000Z",
    }


@pytest.fixture
def client(mock_env):
    """Create a test RaindropClient instance."""
    return RaindropClient(token="test_token_123")


class TestRaindropClient:
    """Test RaindropClient class."""

    def test_init_with_token(self, mock_env):
        """Test client initialization with explicit token."""
        client = RaindropClient(token="custom_token")
        assert client.token == "custom_token"
        assert client.tag == "daily-miku"
        assert client.headers["Authorization"] == "Bearer custom_token"

    def test_init_from_env(self, mock_env):
        """Test client initialization from environment variable."""
        client = RaindropClient()
        assert client.token == "test_token_123"
        assert client.headers["Authorization"] == "Bearer test_token_123"

    def test_init_missing_token(self):
        """Test that missing token raises ValueError."""
        # Patch the module-level RAINDROP_TOKEN variable
        with patch("daily_miku.raindrop.RAINDROP_TOKEN", None):
            with pytest.raises(ValueError, match="RAINDROP_TOKEN"):
                RaindropClient()

    def test_test_connection_success(self, client):
        """Test successful connection test."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
                status_code=200,
            )
            assert client.test_connection() is True

    def test_test_connection_failure(self, client):
        """Test failed connection test."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                status_code=401,
            )
            assert client.test_connection() is False

    def test_fetch_raindrops_success(self, client, sample_raindrop):
        """Test successful fetch of raindrops."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [sample_raindrop], "count": 1},
            )
            items = client.fetch_raindrops(perpage=10, page=0)
            assert len(items) == 1
            assert items[0]["_id"] == 123456
            assert items[0]["title"] == "Hatsune Miku Daily #42"

    def test_fetch_raindrops_with_params(self, client):
        """Test fetch with custom parameters."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
            )
            client.fetch_raindrops(tag="custom-tag", perpage=25, page=1, sort="-title")

            # Verify request was made with correct params
            assert m.last_request.qs["search"] == ["#custom-tag"]
            assert m.last_request.qs["perpage"] == ["25"]
            assert m.last_request.qs["page"] == ["1"]
            assert m.last_request.qs["sort"] == ["-title"]

    def test_fetch_raindrops_error(self, client):
        """Test fetch handles API errors gracefully."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                status_code=500,
            )
            items = client.fetch_raindrops()
            assert items == []

    def test_get_by_date_found(self, client, sample_raindrop):
        """Test getting raindrop by date when found."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [sample_raindrop], "count": 1},
            )
            item = client.get_by_date("2025-01-15")
            assert item is not None
            assert item["_id"] == 123456

    def test_get_by_date_not_found(self, client, sample_raindrop):
        """Test getting raindrop by date when not found."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [sample_raindrop], "count": 1},
            )
            item = client.get_by_date("2025-12-31")
            assert item is None

    def test_get_by_date_invalid_format(self, client):
        """Test get_by_date with invalid date format."""
        item = client.get_by_date("invalid-date")
        assert item is None

    def test_get_today(self, client, sample_raindrop):
        """Test getting today's raindrop."""
        from daily_miku.raindrop import LOCAL_TZ

        # Use the same timezone logic as the application
        now_utc8 = datetime.now(LOCAL_TZ)
        today = now_utc8.strftime("%Y-%m-%d")

        # Create a timestamp that will result in today's date when converted to UTC+8
        # We can just use the current time in UTC+8 and convert back to UTC for the API format
        # Or simpler: just construct a time that is definitely "today" in UTC+8

        # Let's reverse the logic: target date is today (UTC+8)
        # We need a UTC timestamp that converts to this date in UTC+8
        # noon UTC+8 is safe
        noon_utc8 = now_utc8.replace(hour=12, minute=0, second=0, microsecond=0)
        noon_utc = noon_utc8.astimezone(timezone.utc)

        sample_raindrop["created"] = (
            noon_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        )

        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [sample_raindrop], "count": 1},
            )
            item = client.get_today()
            assert item is not None

    def test_format_response_complete(self, client, sample_raindrop):
        """Test formatting a complete raindrop item."""
        result = client.format_response(sample_raindrop, "2025-01-15")

        assert result["date"] == "2025-01-15"
        assert result["imageUrl"] == "https://dailymiku.dev/image/2025-01-15"
        assert result["coverUrl"] == "https://cdn.raindrop.io/test/image.jpg"
        assert result["sourceUrl"] == "https://twitter.com/example/status/123"
        assert result["title"] == "Hatsune Miku Daily #42"
        assert result["description"] == "Beautiful Miku artwork"
        assert result["note"] == "Test note"
        assert result["tags"] == ["daily-miku", "vocaloid"]
        assert result["domain"] == "twitter.com"
        assert result["raindropId"] == 123456
        assert result["timestamp"] == "2025-01-15T12:00:00.000Z"

    def test_format_response_auto_date(self, client, sample_raindrop):
        """Test formatting extracts date from timestamp if not provided."""
        result = client.format_response(sample_raindrop)
        assert result["date"] == "2025-01-15"

    def test_format_response_empty(self, client):
        """Test formatting empty item."""
        result = client.format_response(None)
        assert result == {}

    def test_get_client_factory(self, mock_env):
        """Test get_client factory function."""
        client = get_client()
        assert isinstance(client, RaindropClient)
        assert client.token == "test_token_123"


class TestSimpleCache:
    """Test SimpleCache class."""

    def test_cache_get_set(self):
        """Test basic cache get/set operations."""
        cache = SimpleCache(ttl=10)
        test_data = [{"_id": 1, "title": "test"}]

        cache.set("key1", test_data)
        result = cache.get("key1")

        assert result == test_data

    def test_cache_expires(self):
        """Test cache expiration after TTL."""
        cache = SimpleCache(ttl=1)
        test_data = [{"_id": 1}]

        cache.set("key1", test_data)
        import time

        time.sleep(1.1)

        result = cache.get("key1")
        assert result is None

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = SimpleCache(ttl=10)
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_clear(self):
        """Test clearing cache."""
        cache = SimpleCache(ttl=10)
        cache.set("key1", [{"_id": 1}])
        cache.set("key2", [{"_id": 2}])

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None


class TestRaindropClientCaching:
    """Test caching behavior in RaindropClient."""

    def test_fetch_raindrops_caches_result(self, client):
        """Test that fetch_raindrops caches results."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [{"_id": 1}], "count": 1},
            )

            # First call makes API request
            result1 = client.fetch_raindrops()
            assert len(m.request_history) == 1

            # Second call should use cache
            result2 = client.fetch_raindrops()
            assert len(m.request_history) == 1  # No new request
            assert result1 == result2

    def test_cache_different_params(self, client):
        """Test that different parameters create separate cache keys."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [{"_id": 1}], "count": 1},
            )

            # Different page parameters should hit API twice
            client.fetch_raindrops(page=0)
            client.fetch_raindrops(page=1)

            assert len(m.request_history) == 2

    def test_client_cache_ttl(self, mock_env):
        """Test client respects custom cache TTL."""
        client = RaindropClient(token="test_token", cache_ttl=1)
        assert client.cache_ttl == 1
        assert client.cache.ttl == 1

    def test_clear_cache(self, client):
        """Test clearing client cache."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [{"_id": 1}], "count": 1},
            )

            client.fetch_raindrops()
            client.clear_cache()

            # Cache should be empty
            assert client.cache.get("raindrops:daily-miku:50:0:-created") is None
