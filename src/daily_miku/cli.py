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
    """Send today's daily miku via email (with deduplication)."""
    print("Fetching today's daily miku...")
    client = get_client()
    item = client.get_today()

    if not item:
        today = datetime.now().strftime("%Y-%m-%d")
        print(f"✗ No daily miku found for {today}", file=sys.stderr)
        sys.exit(1)

    formatted = client.format_response(item)
    date = formatted.get("date", "today")
    
    # Check if email for this date was already sent (deduplication)
    cache_dir = Path(os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache")))
    cache_dir = cache_dir / "daily-miku"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    sent_file = cache_dir / f"email-sent-{date}.txt"
    if sent_file.exists():
        print(f"ℹ Email for {date} was already sent today (cached from {sent_file.read_text().strip()})")
        print("Skipping to avoid duplicates.")
        return
    
    print(f"✓ Found: {formatted.get('title', 'Untitled')}")
    print("Sending email...")

    if email_module.send_daily_miku_email(formatted):
        # Mark as sent
        sent_file.write_text(datetime.now().isoformat())
        print("✓ Email sent successfully!")
    else:
        print("✗ Failed to send email", file=sys.stderr)
        sys.exit(1)
