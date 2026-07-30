"""Production ASGI application entrypoint."""

import logging

from .config import DatabaseSettings
from .http import create_app
from .ledger.migrations import MigrationRunner

logger = logging.getLogger("daily_miku.asgi")

# Apply pending database migrations on startup (idempotent, safe for serverless).
try:
    _db_settings = DatabaseSettings.from_environment()
    _runner = MigrationRunner.from_url(
        _db_settings.database_url.get_secret_value(),
        local_pool=not _db_settings.serverless,
    )
    logger.info("Applying database migrations...")
    report = _runner.apply()
    logger.info(
        "Database migrations applied successfully. "
        f"Current version: {report.current_version}, "
        f"newly applied: {report.applied_versions}",
    )
except Exception:
    logger.exception("Database migration failed during startup")
    # In a serverless environment, log the failure but do not crash the import.
    # Image endpoints may return 503 until migrations are applied manually.

app = create_app()
