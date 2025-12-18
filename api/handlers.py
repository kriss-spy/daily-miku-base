"""Simple API handlers without complex dependencies."""

import json
import os
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler
import requests

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

# Load environment variables manually (no dotenv dependency)
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


# Simple raindrop client
def get_today_raindrop():
    """Get today's raindrop with minimal dependencies."""
    token = os.getenv("RAINDROP_TOKEN")
    tag = os.getenv("RAINDROP_TAG", "daily-miku")

    if not token:
        return {"error": "RAINDROP_TOKEN not configured"}

    try:
        headers = {"Authorization": f"Bearer {token}"}
        params = {"search": f"#{tag}", "perpage": 10, "sort": "-created"}

        response = requests.get(
            "https://api.raindrop.io/rest/v1/raindrops/0",
            headers=headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])

        if items:
            item = items[0]
            return {
                "date": "2025-01-15",  # Would extract from timestamp
                "title": item.get("title", ""),
                "cover": item.get("cover", ""),
                "link": item.get("link", ""),
                "excerpt": item.get("excerpt", ""),
                "domain": item.get("domain", ""),
                "tags": item.get("tags", []),
            }
        else:
            return {"error": "No raindrops found"}

    except Exception as e:
        return {"error": str(e)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Route handling
        if self.path == "/health":
            self.health_check()
        elif self.path == "/api/today":
            self.get_today()
        elif self.path == "/api/list":
            self.get_list()
        else:
            self.home()

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

        result = get_today_raindrop()  # Simplified - would get multiple items
        self.wfile.write(json.dumps(result, default=str).encode())

    def home(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        response = {
            "message": "Daily Miku API is running",
            "status": "ok",
            "endpoints": ["/api/today", "/api/list", "/health"],
        }
        self.wfile.write(json.dumps(response).encode())
