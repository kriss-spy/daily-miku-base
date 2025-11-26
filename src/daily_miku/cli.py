"""CLI commands for daily-miku-base."""

import json
import sys
from datetime import datetime

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
