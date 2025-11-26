"""Tests for email automation module."""

import os
import smtplib
from unittest.mock import MagicMock, patch

import pytest

from daily_miku.email import (
    create_html_template,
    is_valid_email,
    send_email,
    send_daily_miku_email,
)


@pytest.fixture
def mock_smtp_env():
    """Mock SMTP environment variables."""
    with patch.dict(
        os.environ,
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "test@example.com",
            "SMTP_PASSWORD": "test_password",
            "EMAIL_FROM": "test@example.com",
            "EMAIL_TO": "recipient@example.com",
        },
    ):
        yield


@pytest.fixture
def sample_miku_data():
    """Sample daily miku data for email testing."""
    return {
        "date": "2025-01-15",
        "imageUrl": "https://dailymiku.dev/image/2025-01-15",
        "coverUrl": "https://cdn.raindrop.io/test/image.jpg",
        "sourceUrl": "https://twitter.com/example/status/123",
        "title": "Hatsune Miku Daily #42",
        "description": "Beautiful Miku artwork",
        "note": "Test note about the artwork",
        "tags": ["daily-miku", "vocaloid"],
        "domain": "twitter.com",
    }


class TestEmailValidation:
    """Test email address validation."""

    def test_valid_emails(self):
        """Test valid email addresses."""
        valid_emails = [
            "user@example.com",
            "test.user@example.co.uk",
            "user+tag@example.com",
            "user_name@example-domain.com",
            "123@example.com",
        ]
        for email in valid_emails:
            assert is_valid_email(email) is True, f"Should accept {email}"

    def test_invalid_emails(self):
        """Test invalid email addresses."""
        invalid_emails = [
            "notanemail",
            "@example.com",
            "user@",
            "user @example.com",
            "user@example",
            "user..name@example.com",
            "nonexistforreal!!!@qqq.com",  # Invalid characters
        ]
        for email in invalid_emails:
            assert is_valid_email(email) is False, f"Should reject {email}"


class TestHTMLTemplate:
    """Test HTML email template generation."""

    def test_create_template_complete_data(self, sample_miku_data):
        """Test template creation with complete data."""
        html = create_html_template(sample_miku_data)
        
        # Check for key elements
        assert "Hatsune Miku Daily #42" in html
        assert "2025-01-15" in html
        assert "https://cdn.raindrop.io/test/image.jpg" in html
        assert "https://twitter.com/example/status/123" in html
        assert "Beautiful Miku artwork" in html
        assert "Test note about the artwork" in html
        assert "twitter.com" in html
        
        # Check for HTML structure
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "background: linear-gradient" in html  # Purple gradient

    def test_create_template_minimal_data(self):
        """Test template with minimal data."""
        minimal_data = {
            "date": "2025-01-15",
            "coverUrl": "https://example.com/image.jpg",
        }
        html = create_html_template(minimal_data)
        
        assert "2025-01-15" in html
        assert "https://example.com/image.jpg" in html
        assert "<!DOCTYPE html>" in html

    def test_create_template_missing_optional_fields(self):
        """Test template handles missing optional fields gracefully."""
        data = {
            "date": "2025-01-15",
            "coverUrl": "https://example.com/image.jpg",
            "title": "",
            "description": "",
            "note": "",
            "sourceUrl": "",
        }
        html = create_html_template(data)
        assert "<!DOCTYPE html>" in html
        assert "2025-01-15" in html


class TestSendEmail:
    """Test email sending functionality."""

    def test_send_email_success(self, mock_smtp_env):
        """Test successful email sending."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server
            
            result = send_email(
                to_email="test@example.com",
                subject="Test Subject",
                html_body="<html><body>Test</body></html>",
            )
            
            assert result is True
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with(
                "test@example.com", "test_password"
            )
            mock_server.send_message.assert_called_once()

    def test_send_email_invalid_recipient(self, mock_smtp_env):
        """Test email sending with invalid recipient."""
        result = send_email(
            to_email="invalid-email",
            subject="Test",
            html_body="<html>Test</html>",
        )
        assert result is False

    def test_send_email_smtp_error(self, mock_smtp_env):
        """Test email sending handles SMTP errors."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_smtp.return_value.__enter__.side_effect = smtplib.SMTPException(
                "Connection failed"
            )
            
            result = send_email(
                to_email="test@example.com",
                subject="Test",
                html_body="<html>Test</html>",
            )
            assert result is False

    def test_send_email_missing_env_vars(self):
        """Test email sending fails with missing environment variables."""
        with patch.dict(os.environ, {}, clear=True):
            result = send_email(
                to_email="test@example.com",
                subject="Test",
                html_body="<html>Test</html>",
            )
            assert result is False


class TestSendDailyMikuEmail:
    """Test daily miku email wrapper."""

    def test_send_daily_miku_email_success(self, mock_smtp_env, sample_miku_data):
        """Test sending daily miku email."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server
            
            result = send_daily_miku_email(sample_miku_data)
            
            assert result is True
            mock_server.send_message.assert_called_once()
            
            # Check that subject contains the date
            call_args = mock_server.send_message.call_args
            msg = call_args[0][0]
            assert "2025-01-15" in msg["Subject"]

    def test_send_daily_miku_email_default_recipient(
        self, mock_smtp_env, sample_miku_data
    ):
        """Test sending to default recipient from env."""
        with patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server
            
            result = send_daily_miku_email(sample_miku_data)
            
            assert result is True
            call_args = mock_server.send_message.call_args
            msg = call_args[0][0]
            assert msg["To"] == "recipient@example.com"
