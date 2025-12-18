"""Tests for FastAPI endpoints."""

import os
from datetime import datetime

import pytest
import requests_mock
from starlette.testclient import TestClient

# Mock environment before importing the app
os.environ["RAINDROP_TOKEN"] = "test_token_123"

from daily_miku.server import app  # noqa: E402


@pytest.fixture
def client():
    """Create FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def sample_raindrop():
    """Sample raindrop item."""
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
def mock_raindrop_api(sample_raindrop):
    """Mock Raindrop.io API responses."""
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.raindrop.io/rest/v1/raindrops/0",
            json={"items": [sample_raindrop], "count": 1},
        )
        yield m


class TestRootEndpoint:
    """Test root API endpoint."""

    def test_root_returns_api_info(self, client):
        """Test root endpoint returns API information."""
        response = client.get("/")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "daily-miku-base API"
        assert data["version"] == "0.1.0"
        assert "endpoints" in data
        assert "/api/image/{date}" in data["endpoints"].values()


class TestImageMetadataEndpoint:
    """Test /api/image/{date} endpoint."""

    def test_get_image_metadata_success(self, client, mock_raindrop_api):
        """Test getting image metadata for a specific date."""
        response = client.get("/api/image/2025-01-15")
        assert response.status_code == 200

        data = response.json()
        assert data["date"] == "2025-01-15"
        assert data["title"] == "Hatsune Miku Daily #42"
        assert data["coverUrl"] == "https://cdn.raindrop.io/test/image.jpg"
        assert data["raindropId"] == 123456

    def test_get_image_metadata_not_found(self, client):
        """Test 404 when image not found for date."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
            )
            response = client.get("/api/image/2025-12-31")
            assert response.status_code == 404
            assert "No daily miku found" in response.json()["detail"]


class TestImageFileEndpoint:
    """Test /image/{date} redirect endpoint."""

    def test_get_image_file_redirect(self, client, mock_raindrop_api):
        """Test image file endpoint returns redirect."""
        response = client.get("/image/2025-01-15", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "https://cdn.raindrop.io/test/image.jpg"

    def test_get_image_file_not_found(self, client):
        """Test 404 when image not found."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
            )
            response = client.get("/image/2025-12-31")
            assert response.status_code == 404


class TestWeekEndpoint:
    """Test /api/week/{week} endpoint."""

    def test_get_week_images_success(self, client, mock_raindrop_api):
        """Test getting images for a week."""
        response = client.get("/api/week/2025-W03")
        assert response.status_code == 200

        data = response.json()
        assert data["week"] == "2025-W03"
        assert "images" in data
        assert "count" in data
        assert isinstance(data["images"], list)

    def test_get_week_images_invalid_format(self, client):
        """Test invalid week format."""
        response = client.get("/api/week/invalid")
        assert response.status_code == 400
        assert "Invalid week format" in response.json()["detail"]


class TestMonthEndpoint:
    """Test /api/month/{month} endpoint."""

    def test_get_month_images_success(self, client, mock_raindrop_api):
        """Test getting images for a month."""
        response = client.get("/api/month/2025-01")
        assert response.status_code == 200

        data = response.json()
        assert data["month"] == "2025-01"
        assert "images" in data
        assert "count" in data
        assert isinstance(data["images"], list)

    def test_get_month_images_invalid_format(self, client):
        """Test invalid month format."""
        response = client.get("/api/month/invalid")
        assert response.status_code == 400
        assert "Invalid month format" in response.json()["detail"]

    def test_get_month_images_invalid_month_number(self, client):
        """Test invalid month number."""
        response = client.get("/api/month/2025-13")
        assert response.status_code == 400


class TestYearEndpoint:
    """Test /api/year/{year} endpoint."""

    def test_get_year_images_success(self, client, mock_raindrop_api):
        """Test getting images for a year."""
        response = client.get("/api/year/2025")
        assert response.status_code == 200

        data = response.json()
        assert data["year"] == 2025
        assert "images" in data
        assert "count" in data
        assert isinstance(data["images"], list)

    def test_get_year_images_out_of_range(self, client):
        """Test year out of valid range."""
        response = client.get("/api/year/2050")
        assert response.status_code == 400
        assert "must be between" in response.json()["detail"]


class TestTodayEndpoint:
    """Test /today redirect endpoint."""

    def test_get_today_redirect(self, client):
        """Test today endpoint redirects to today's date."""
        today = datetime.now().strftime("%Y-%m-%d")
        response = client.get("/today", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == f"/{today}"


class TestLatestEndpoint:
    """Test /latest endpoint."""

    def test_get_latest_success(self, client, mock_raindrop_api):
        """Test getting latest image."""
        response = client.get("/latest")
        assert response.status_code == 200

        data = response.json()
        assert "date" in data
        assert "title" in data
        assert data["title"] == "Hatsune Miku Daily #42"

    def test_get_latest_empty(self, client):
        """Test latest when no images exist."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
            )
            response = client.get("/latest")
            assert response.status_code == 404


class TestRandomEndpoint:
    """Test /random endpoint."""

    def test_get_random_success(self, client, mock_raindrop_api):
        """Test getting random image."""
        response = client.get("/random")
        assert response.status_code == 200

        data = response.json()
        assert "title" in data
        assert data["title"] == "Hatsune Miku Daily #42"

    def test_get_random_empty(self, client):
        """Test random when no images exist."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
            )
            response = client.get("/random")
            assert response.status_code == 404


class TestStatsEndpoint:
    """Test /api/stats endpoint."""

    def test_get_stats_success(self, client, mock_raindrop_api):
        """Test getting collection statistics."""
        response = client.get("/api/stats")
        assert response.status_code == 200

        data = response.json()
        assert "total" in data
        assert "dateRange" in data
        assert "tags" in data
        assert data["total"] == 1
        assert isinstance(data["tags"], list)

    def test_get_stats_empty_collection(self, client):
        """Test stats with empty collection."""
        with requests_mock.Mocker() as m:
            m.get(
                "https://api.raindrop.io/rest/v1/raindrops/0",
                json={"items": [], "count": 0},
            )
            response = client.get("/api/stats")
            assert response.status_code == 200

            data = response.json()
            assert data["total"] == 0
            assert data["dateRange"] is None


class TestCORS:
    """Test CORS middleware."""

    def test_cors_headers_present(self, client):
        """Test that CORS headers are set."""
        response = client.options("/", headers={"Origin": "https://example.com"})
        assert "access-control-allow-origin" in response.headers
