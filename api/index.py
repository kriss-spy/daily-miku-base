"""Vercel serverless entrypoint.

This file imports the FastAPI app from the source directory directly.
Vercel's Python runtime discovers and runs the ASGI `app` exposed here.

The sys.path manipulation allows importing from ../src even though Vercel
doesn't install the package in editable mode.
"""
import sys
from pathlib import Path

# Add src directory to Python path so we can import daily_miku module
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from daily_miku.server import app  # noqa: E402

__all__ = ["app"]