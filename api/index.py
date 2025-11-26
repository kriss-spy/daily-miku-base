"""Vercel serverless entrypoint.

This file re-exports the ASGI `app` from the package so Vercel's Python
runtime can discover and run the FastAPI application.

Vercel will route requests to this file when configured in `vercel.json`.
"""
from daily_miku.server import app  # re-export the ASGI app for Vercel


__all__ = ["app"]
