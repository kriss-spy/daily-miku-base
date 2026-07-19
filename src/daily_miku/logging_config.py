"""Logging configuration for daily-miku-base."""

import json
import logging
import sys
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

request_id_context: ContextVar[str] = ContextVar("request_id", default="")


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            log_data["request_id"] = request_id

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
    logger.propagate = False

    return logger


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def set_request_id(request_id: str) -> Token[str]:
    """Set the request ID for the current context."""
    return request_id_context.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """Restore the request ID context that preceded a request."""
    request_id_context.reset(token)


def get_request_id() -> str:
    """Get the current request ID."""
    return request_id_context.get()


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
