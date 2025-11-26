"""Tests for Raindrop.io API client."""

import os
from datetime import datetime
from unittest.mock import patch

import pytest
import requests_mock

# Clear any loaded environment before importing the module
os.environ.pop("RAINDROP_TOKEN", None)

from daily_miku.raindrop import RaindropClient, get_client


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
        with patch.dict(os.environ, {}, clear=True):
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
        today = datetime.now().strftime("%Y-%m-%d")
        sample_raindrop["created"] = datetime.now().isoformat() + "Z"
        
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
