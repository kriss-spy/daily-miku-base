"""Simple Vercel serverless function without complex dependencies."""

import json
from http.server import BaseHTTPRequestHandler


# Simple response handler
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Set response headers
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        # Simple response
        response = {
            "message": "Daily Miku API is running",
            "status": "ok",
            "endpoints": ["/api/today", "/api/list", "/health"],
        }

        self.wfile.write(json.dumps(response).encode())

    def do_POST(self):
        self.send_response(404)
        self.send_header("Content-type", "application/json")
        self.end_headers()

        response = {"error": "Not found"}
        self.wfile.write(json.dumps(response).encode())
