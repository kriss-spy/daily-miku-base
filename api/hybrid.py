"""Simple frontend handler with basic HTML."""

import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

# Add src directory to Python path
current_dir = Path(__file__).resolve().parent
possible_src_paths = [
    current_dir / "src",
    current_dir.parent / "src",
]
src_path = None
for path in possible_src_paths:
    if path.exists():
        src_path = path
        break

if src_path:
    sys.path.insert(0, str(src_path))

# Load environment variables manually
try:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value
except Exception:
    pass


# API functions
def get_raindrops(limit=10):
    """Get raindrops with minimal dependencies."""
    token = os.getenv("RAINDROP_TOKEN")
    tag = os.getenv("RAINDROP_TAG", "daily-miku")

    if not token:
        return {"error": "RAINDROP_TOKEN not configured"}

    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {"search": f"#{tag}", "perpage": limit, "sort": "-lastUpdate"}

        response = requests.get(
            "https://api.raindrop.io/rest/v1/raindrops/0",
            headers=headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])

        # Format items
        formatted_items = []
        for item in items:
            # Extract date from lastUpdate timestamp (when the raindrop was saved/updated)
            lastUpdate = item.get("lastUpdate", "")
            if lastUpdate:
                # Parse ISO 8601 and convert to local date (GMT+8)
                try:
                    utc_time = datetime.fromisoformat(lastUpdate.replace("Z", "+00:00"))
                    local_time = utc_time.astimezone(timezone(timedelta(hours=8)))
                    date = local_time.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    date = lastUpdate.split("T")[0] if "T" in lastUpdate else lastUpdate
            else:
                date = ""

            formatted_item = {
                "date": date,
                "title": item.get("title", ""),
                "cover": item.get("cover", ""),
                "link": item.get("link", ""),
                "excerpt": item.get("excerpt", ""),
                "domain": item.get("domain", ""),
                "tags": item.get("tags", []),
                "raindropId": item.get("_id"),
                "timestamp": item.get("created", ""),
            }
            formatted_items.append(formatted_item)

        return formatted_items

    except Exception as e:
        return {"error": str(e)}


def get_today_raindrop():
    """Get today's raindrop."""
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    items = get_raindrops(50)
    if isinstance(items, dict) and "error" in items:
        return items

    # Find item matching today's date
    for item in items:
        if item.get("date") == today:
            return item

    return {"error": "No raindrop found for today"}


def get_raindrop_by_date(date_str):
    """Get raindrop for specific date."""
    items = get_raindrops(50)  # Get more items to search
    if isinstance(items, dict) and "error" in items:
        return items

    # Find item matching the date
    for item in items:
        if item.get("date") == date_str:
            return item

    return {"error": "No miku found for this date"}


def is_date_path(path):
    """Check if path is a valid date format (YYYY-MM-DD)."""
    if not path:
        return False

    try:
        parts = path.split("/")
        date_str = parts[-1] if parts[-1] else parts[-2] if len(parts) > 1 else path

        # Try to parse as date
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def generate_miku_html(data, page_title="Daily Miku"):
    """Generate miku page HTML for any data."""
    if isinstance(data, dict) and "error" in data:
        return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            background: linear-gradient(135deg, #0f172a 0%, #1a1f3a 100%);
            color: #e2e8f0; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6; min-height: 100vh;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        header {{ text-align: center; margin-bottom: 3rem; }}
        h1 {{ font-size: 2.5rem; background: linear-gradient(135deg, #9945ff 0%, #ec4899 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .empty-state {{ text-align: center; padding: 3rem; color: #94a3b8; }}
        .nav {{ text-align: center; margin-top: 2rem; }}
        .nav a {{ background: #9945ff; color: white; padding: 1rem 2rem; text-decoration: none; border-radius: 8px; margin: 0 0.5rem; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎵 Daily Miku</h1>
            <p>Beautiful Hatsune Miku artwork every day</p>
        </header>
        <div class="empty-state">
            <h2>No Daily Miku Found</h2>
            <p>Unable to fetch Daily Miku image. Please check back later.</p>
            <p>Error: {data.get("error", "Unknown error")}</p>
        </div>
        <div class="nav">
            <a href="/today">Today</a>
            <a href="/list">View All</a>
            <a href="/api/today">API</a>
        </div>
    </div>
</body>
</html>
        """

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title} - {data.get("title", "Daily Miku")}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            background: linear-gradient(135deg, #0f172a 0%, #1a1f3a 100%);
            color: #e2e8f0; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6; min-height: 100vh;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        header {{ text-align: center; margin-bottom: 3rem; }}
        h1 {{ font-size: 2.5rem; background: linear-gradient(135deg, #9945ff 0%, #ec4899 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .image-container {{ text-align: center; margin-bottom: 2rem; }}
        .image-container img {{ max-width: 100%; max-height: 600px; border-radius: 8px; }}
        .metadata {{ background: #1e293b; padding: 2rem; border-radius: 12px; max-width: 600px; margin: 0 auto; }}
        .metadata h2 {{ color: #9945ff; margin-bottom: 1rem; }}
        .metadata-item {{ margin-bottom: 1rem; }}
        .metadata-label {{ color: #94a3b8; font-size: 0.85rem; text-transform: uppercase; }}
        .metadata-value {{ margin-top: 0.5rem; }}
        .metadata-value a {{ color: #9945ff; text-decoration: none; }}
        .nav {{ text-align: center; margin-top: 2rem; }}
        .nav a {{ background: #9945ff; color: white; padding: 1rem 2rem; text-decoration: none; border-radius: 8px; margin: 0 0.5rem; }}
        .date {{ color: #94a3b8; margin-top: 1rem; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎵 Daily Miku</h1>
            <p>Beautiful Hatsune Miku artwork every day</p>
        </header>
        <div class="image-container">
            <img src="{data.get("cover", "")}" alt="{data.get("title", "Daily Miku")}" loading="lazy">
            <div class="date">{data.get("date", "")}</div>
        </div>
        <div class="metadata">
            <h2>{data.get("title", "Daily Miku")}</h2>
            {f'<div class="metadata-item"><div class="metadata-label">Description</div><div class="metadata-value">{data.get("excerpt", "")}</div></div>' if data.get("excerpt") else ""}
            {f'<div class="metadata-item"><div class="metadata-label">Source</div><div class="metadata-value"><a href="{data.get("link", "")}" target="_blank">View Original</a></div></div>' if data.get("link") else ""}
        </div>
        <div class="nav">
            <a href="/today">Today</a>
            <a href="/list">View All</a>
            <a href="/api/today">API</a>
        </div>
    </div>
</body>
</html>
    """


def generate_list_html(items):
    """Generate list page HTML."""
    if isinstance(items, dict) and "error" in items:
        items = []

    item_html = ""
    for item in items[:20]:  # Show first 20 items
        cover_url = item.get("cover", "")
        item_html += f"""
        <div style="background: #1e293b; border-radius: 12px; overflow: hidden; margin-bottom: 1.5rem; border: 1px solid rgba(255, 255, 255, 0.1);">
            {f'<a href="/{item.get("date", "")}"><img src="{cover_url}" style="width: 100%; height: 250px; object-fit: cover; display: block;" alt="{item.get("title", "")}" loading="lazy"></a>' if cover_url else ""}
            <div style="padding: 1.5rem;">
                <h3 style="color: #9945ff; margin-bottom: 0.5rem; font-size: 1.1rem;">
                    <a href="/{item.get("date", "")}" style="color: #9945ff; text-decoration: none;">{item.get("title", "Untitled")}</a>
                </h3>
                <div style="color: #94a3b8; font-size: 0.9rem; margin-bottom: 0.75rem;">{item.get("date", "")}</div>
                {f'<p style="color: #cbd5e1; margin-bottom: 1rem; font-size: 0.9rem;">{item.get("excerpt", "")}</p>' if item.get("excerpt") else ""}
                {f'<a href="{item.get("link", "")}" style="color: #9945ff; text-decoration: none; font-size: 0.9rem; border-bottom: 1px solid rgba(153, 69, 255, 0.3);" target="_blank">View Original</a>' if item.get("link") else ""}
            </div>
        </div>
        """

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Miku - Recent Images</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            background: linear-gradient(135deg, #0f172a 0%, #1a1f3a 100%);
            color: #e2e8f0; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6; min-height: 100vh;
        }}
        .container {{ max-width: 900px; margin: 0 auto; padding: 2rem; }}
        header {{ text-align: center; margin-bottom: 3rem; }}
        h1 {{ font-size: 2.5rem; background: linear-gradient(135deg, #9945ff 0%, #ec4899 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 0.5rem; }}
        .nav {{ text-align: center; margin-top: 2rem; }}
        .nav a {{ background: #9945ff; color: white; padding: 1rem 2rem; text-decoration: none; border-radius: 8px; margin: 0 0.5rem; display: inline-block; transition: background 0.2s; }}
        .nav a:hover {{ background: #8034e6; }}
        .list-container {{ margin-bottom: 2rem; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎵 Daily Miku</h1>
            <p>Recent Daily Miku images</p>
        </header>
        <div class="list-container">
        {item_html if item_html else '<div style="text-align: center; padding: 3rem; color: #94a3b8;"><h2>No Images Found</h2><p>Unable to fetch Daily Miku images.</p></div>'}
        </div>
        <div class="nav">
            <a href="/today">Today</a>
            <a href="/api/list">API</a>
        </div>
    </div>
</body>
</html>
    """


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse URL
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        # Route handling
        if path == "/health":
            self.health_check()
        elif path == "/api/today":
            self.get_today()
        elif path == "/api/list":
            self.get_list()
        elif path == "/" or path == "/today":
            self.today_page()
        elif path.startswith("/image/"):
            self.image_page(path.split("/")[-1])
        elif path == "/list":
            self.list_page()
        elif is_date_path(path):
            self.date_page(path.lstrip("/"))
        else:
            self.not_found()

    def health_check(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        response = {"status": "healthy"}
        self.wfile.write(json.dumps(response).encode())

    def get_today(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        result = get_today_raindrop()
        self.wfile.write(json.dumps(result, default=str).encode())

    def get_list(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        result = get_raindrops(10)
        self.wfile.write(json.dumps(result, default=str).encode())

    def today_page(self):
        """Serve today's page."""
        today_data = get_today_raindrop()
        html = generate_miku_html(today_data, "Daily Miku")

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def date_page(self, date_str):
        """Serve page for specific date."""
        data = get_raindrop_by_date(date_str)
        html = generate_miku_html(data, f"Daily Miku - {date_str}")

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def image_page(self, date):
        """Serve the actual image file (fetch from Raindrop CDN)."""
        data = get_raindrop_by_date(date)

        if isinstance(data, dict) and "error" in data:
            self.send_response(404)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"No image found for {date}".encode())
            return

        cover_url = data.get("cover", "")
        if not cover_url:
            self.send_response(404)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Image URL not available")
            return

        # Fetch image from Raindrop CDN and serve directly
        try:
            response = requests.get(cover_url, timeout=30)
            response.raise_for_status()

            # Determine content type from response or URL
            content_type = response.headers.get("content-type", "image/jpeg")

            self.send_response(200)
            self.send_header("Content-type", content_type)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        except requests.RequestException as e:
            self.send_response(502)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Failed to fetch image: {str(e)}".encode())

    def list_page(self):
        """Serve list page."""
        items = get_raindrops(20)
        html = generate_list_html(items)

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def not_found(self):
        self.send_response(404)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        html = "<h1>404 - Page Not Found</h1>"
        self.wfile.write(html.encode())
