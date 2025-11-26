"""Logging configuration for daily-miku-base."""

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

# Request context variables
request_id_context: str = ""


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available
        if request_id_context:
            log_data["request_id"] = request_id_context

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        extra = getattr(record, "extra_fields", None)
        if extra and isinstance(extra, dict):
            log_data.update(extra)

        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Set up JSON logging."""
    logger = logging.getLogger("daily_miku")
    logger.setLevel(log_level)

    # Remove any existing handlers
    logger.handlers = []

    # Console handler with JSON formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)

    return logger


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def set_request_id(request_id: str) -> None:
    """Set the request ID for the current context."""
    global request_id_context
    request_id_context = request_id


def get_request_id() -> str:
    """Get the current request ID."""
    return request_id_context


def log_with_context(
    logger: logging.Logger, level: str, message: str, **extra_fields
) -> None:
    """Log a message with additional context."""
    record = logging.LogRecord(
        name=logger.name,
        level=getattr(logging, level.upper()),
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    if extra_fields:
        record.extra_fields = extra_fields
    logger.handle(record)
