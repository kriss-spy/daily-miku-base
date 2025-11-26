"""Vercel serverless entrypoint.

This file attempts to import the ASGI `app` from the package so Vercel's
Python runtime can discover and run the FastAPI application. If the import
fails (for example due to missing environment variables or dependency
errors), we expose a small fallback FastAPI app that returns an informative
error message instead of crashing the serverless function with an opaque
500 error.

This helps with debugging deployments on Vercel because the HTTP response
will include the original exception message.
"""
from fastapi import FastAPI
import traceback


def _make_error_app(err: Exception) -> FastAPI:
	app = FastAPI(title="daily-miku-base (import error)")

	@app.get("/")
	async def import_error_root():
		return {
			"error": "failed to import application",
			"detail": str(err),
			"trace": traceback.format_exc(),
		}

	return app


try:
	# Try to import the real FastAPI app
	from daily_miku.server import app  # type: ignore
except Exception as exc:  # pragma: no cover - runtime only
	# Fallback app that surfaces the import error
	app = _make_error_app(exc)


__all__ = ["app"]
