"""Production ASGI application entrypoint."""

import logging

from .config import DatabaseSettings
from .http import create_app
from .ledger.migrations import MigrationRunner

logger = logging.getLogger("daily_miku.asgi")

# Apply pending database migrations on startup (idempotent, safe for serverless).
_db_settings = DatabaseSettings.from_environment()
_runner = MigrationRunner.from_url(
    _db_settings.database_url.get_secret_value(),
    local_pool=not _db_settings.serverless,
)
logger.info("Applying database migrations...")
_runner.apply()
logger.info("Database migrations applied successfully.")

app = create_app()
