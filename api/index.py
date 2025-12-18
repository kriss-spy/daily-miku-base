"""Vercel serverless entrypoint.

This file imports the FastAPI app from the source directory directly.
Vercel's Python runtime discovers and runs the ASGI `app` exposed here.

The sys.path manipulation allows importing from ../src even though Vercel
doesn't install the package in editable mode.
"""

import sys
from pathlib import Path
from mangum import Mangum

# Add src directory to Python path so we can import daily_miku module
# Handle both local development and Vercel deployment (flattened or preserved)
current_dir = Path(__file__).resolve().parent
possible_src_paths = [
    current_dir / "src",
    current_dir.parent / "src",
    current_dir.parent.parent / "src",
]
src_path = None
for path in possible_src_paths:
    if path.exists():
        src_path = path
        break

if src_path:
    sys.path.insert(0, str(src_path))

from daily_miku.server import app  # noqa: E402

handler = Mangum(app)
