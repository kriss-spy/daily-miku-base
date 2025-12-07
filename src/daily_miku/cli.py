"""CLI commands for daily-miku-base."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import email as email_module
from .raindrop import get_client


def fetch_today():
    """Fetch and display today's daily miku."""
    client = get_client()
    item = client.get_today()

    if item:
        formatted = client.format_response(item)
        print(json.dumps(formatted, indent=2))
    else:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"No daily miku found for {today}", file=sys.stderr)
        sys.exit(1)


def fetch_date(date: str):
    """Fetch and display daily miku for a specific date."""
    client = get_client()
    item = client.get_by_date(date)

    if item:
        formatted = client.format_response(item, date)
        print(json.dumps(formatted, indent=2))
    else:
        print(f"No daily miku found for {date}", file=sys.stderr)
        sys.exit(1)


def test_connection():
    """Test Raindrop.io API connection."""
    print("Testing connection to Raindrop.io...")
    client = get_client()

    if client.test_connection():
        print("✓ Connection successful!")
        print(f"  Token: {client.token[:10]}...")
        print(f"  Tag: #{client.tag}")

        # Fetch a sample to verify tag works
        items = client.fetch_raindrops(perpage=1)
        if items:
            print(f"✓ Found bookmarks with #{client.tag} tag")
            print(f"  Latest: {items[0].get('title', 'Untitled')}")
        else:
            print(f"⚠ No bookmarks found with #{client.tag} tag")
    else:
        print("✗ Connection failed!", file=sys.stderr)
        sys.exit(1)


def list_recent(limit: int = 10):
    """List recent daily miku bookmarks."""
    client = get_client()
    items = client.fetch_raindrops(perpage=limit)

    if not items:
        print("No bookmarks found", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(items)} recent bookmarks:\n")
    for item in items:
        created = item.get("created", "")
        if created:
            date = datetime.fromisoformat(created.replace("Z", "+00:00")).strftime(
                "%Y-%m-%d"
            )
        else:
            date = "Unknown"

        title = item.get("title", "Untitled")
        link = item.get("link", "")
        print(f"  {date}: {title}")
        print(f"    Source: {link}")
        print()


def send_email():
    """Send today's daily miku via email with failure tracking."""
    from datetime import timezone, timedelta

    # Use UTC+8 timezone (Asia)
    LOCAL_TZ = timezone(timedelta(hours=8))
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    print(f"Fetching daily miku for {today}...")
    client = get_client()
    item = client.get_today()

    # Check if we have a miku for today
    if not item:
        print(f"✗ No daily miku found for {today}", file=sys.stderr)

        # Track failure
        cache_dir = Path.home() / ".cache" / "daily-miku"
        cache_dir.mkdir(parents=True, exist_ok=True)
        failure_file = cache_dir / f"email-failed-{today}.txt"

        # Count failures
        failure_count = 0
        if failure_file.exists():
            content = failure_file.read_text().strip()
            try:
                failure_count = int(content)
            except ValueError:
                failure_count = 0

        failure_count += 1
        failure_file.write_text(str(failure_count))

        print(f"⚠ This is failure #{failure_count} for today")

        # Send warning email on second failure
        if failure_count >= 2:
            print("Sending warning email...")
            if email_module.send_warning_email(
                today, f"No daily miku found for {today}"
            ):
                print("✓ Warning email sent to EMAIL_FROM")
            else:
                print("✗ Failed to send warning email", file=sys.stderr)

        sys.exit(1)

    # Found miku, send email
    formatted = client.format_response(item)
    print(f"✓ Found: {formatted.get('title', 'Untitled')}")
    print("Sending email...")

    if email_module.send_daily_miku_email(formatted):
        print("✓ Email sent successfully!")

        # Clear failure tracking on success
        cache_dir = Path.home() / ".cache" / "daily-miku"
        failure_file = cache_dir / f"email-failed-{today}.txt"
        if failure_file.exists():
            failure_file.unlink()
            print("✓ Cleared failure tracking")
    else:
        print("✗ Failed to send email", file=sys.stderr)
        sys.exit(1)
