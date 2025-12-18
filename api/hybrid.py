"""Hybrid handler - serves frontend templates and API endpoints."""

import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

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
except:
    pass


# Template rendering
def render_template(template_name, context=None):
    """Simple template rendering."""
    if not src_path:
        return "<h1>Templates directory not found</h1>"
    template_path = src_path / "daily_miku" / "templates" / template_name

    try:
        with open(template_path, "r") as f:
            template_content = f.read()

        if context:
            # Simple variable replacement ({{ variable }})
            for key, value in context.items():
                template_content = template_content.replace(
                    f"{{{{ {key} }}}}", str(value)
                )

        return template_content
    except FileNotFoundError:
        return f"<h1>Template {template_name} not found</h1>"


# API functions
def get_raindrops(limit=10):
    """Get raindrops with minimal dependencies."""
    token = os.getenv("RAINDROP_TOKEN")
    tag = os.getenv("RAINDROP_TAG", "daily-miku")

    if not token:
        return {"error": "RAINDROP_TOKEN not configured"}

    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {"search": f"#{tag}", "perpage": limit, "sort": "-created"}

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
            # Extract date from created timestamp
            created = item.get("created", "")
            if created:
                # Parse ISO 8601 and convert to local date
                try:
                    utc_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    local_time = utc_time.astimezone(timezone(timedelta(hours=8)))
                    date = local_time.strftime("%Y-%m-%d")
                except:
                    date = created.split("T")[0] if "T" in created else created
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
                "timestamp": created,
            }
            formatted_items.append(formatted_item)

        return formatted_items

    except Exception as e:
        return {"error": str(e)}


def get_today_raindrop():
    """Get today's raindrop."""
    items = get_raindrops(10)
    if isinstance(items, dict) and "error" in items:
        return items

    # Get first item (most recent)
    if items:
        return items[0]
    else:
        return {"error": "No raindrops found"}


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
        elif path == "/":
            self.home_page()
        elif path.startswith("/image/"):
            self.image_page(path.split("/")[-1])
        elif path == "/list":
            self.list_page()
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

    def home_page(self):
        """Serve home page with today's image."""
        today_data = get_today_raindrop()

        # Handle both dict and error cases
        if isinstance(today_data, dict) and "error" in today_data:
            context = {
                "title": "Daily Miku",
                "image_url": "",
                "date": "",
                "description": "",
                "source_url": "",
            }
        else:
            context = {
                "title": today_data.get("title", "Daily Miku")
                if isinstance(today_data, dict)
                else "Daily Miku",
                "image_url": today_data.get("cover", "")
                if isinstance(today_data, dict)
                else "",
                "date": today_data.get("date", "")
                if isinstance(today_data, dict)
                else "",
                "description": today_data.get("excerpt", "")
                if isinstance(today_data, dict)
                else "",
                "source_url": today_data.get("link", "")
                if isinstance(today_data, dict)
                else "",
            }

        html = render_template("home.html", context)

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def image_page(self, date):
        """Serve specific image page."""
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        html = render_template("image.html", {"date": date})
        self.wfile.write(html.encode())

    def list_page(self):
        """Serve list page."""
        items = get_raindrops(20)

        if isinstance(items, dict) and "error" in items:
            context = {"items": []}
        else:
            context = {"items": items}

        html = render_template("list.html", context)

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
