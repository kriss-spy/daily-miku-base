"""Vercel ASGI entrypoint for the v2 application."""

import sys
from pathlib import Path

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

from daily_miku.asgi import app  # noqa: E402, F401
