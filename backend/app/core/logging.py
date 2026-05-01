"""
app/core/logging.py

Structured logging configuration.

Design decisions:
  - JSON format in production for log aggregators (Datadog, Papertrail, etc.).
  - Human-readable text format in development.
  - Request-ID injected into every log record via a thread-local filter.
  - Configures the root logger so all app modules inherit the settings.
  - Called ONCE in create_app() before any other setup.

Usage:
    from app.core.logging import configure_logging
    configure_logging(level="INFO", fmt="json")

    import logging
    logger = logging.getLogger(__name__)
    logger.info("Job created", extra={"job_id": "abc123"})
"""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Request-ID context variable
# ─────────────────────────────────────────────────────────────────────────────

# Thread-safe context variable — set at the start of each HTTP request
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(rid: str) -> None:
    """Set the current request's correlation ID."""
    request_id_var.set(rid)


def get_request_id() -> str:
    """Get the current request's correlation ID."""
    return request_id_var.get()


# ─────────────────────────────────────────────────────────────────────────────
# Custom log filter — injects request_id into every record
# ─────────────────────────────────────────────────────────────────────────────

class RequestIdFilter(logging.Filter):
    """Injects request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


# ─────────────────────────────────────────────────────────────────────────────
# JSON Formatter
# ─────────────────────────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON.

    Each record produces:
    {
        "timestamp": "2024-01-01T00:00:00.000Z",
        "level": "INFO",
        "logger": "app.api.v1.resume",
        "request_id": "a1b2c3d4",
        "message": "Resume parsed successfully",
        "module": "resume",
        "function": "parse_resume",
        "line": 42,
        ...extra fields from log call...
    }
    """

    # Standard fields to exclude from the "extra" dump to avoid duplication
    _STDLIB_FIELDS = frozenset({
        "name", "msg", "args", "levelname", "levelno",
        "pathname", "filename", "module", "exc_info", "exc_text",
        "stack_info", "lineno", "funcName", "created", "msecs",
        "relativeCreated", "thread", "threadName", "processName",
        "process", "message", "asctime", "request_id", "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level":      record.levelname,
            "logger":     record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message":    record.message,
            "module":     record.module,
            "function":   record.funcName,
            "line":       record.lineno,
        }

        # Attach exception info if present
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Attach any extra fields passed via logger.info("msg", extra={...})
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in self._STDLIB_FIELDS
        }
        if extras:
            payload["extra"] = extras

        return json.dumps(payload, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# Text Formatter (development)
# ─────────────────────────────────────────────────────────────────────────────

_TEXT_FORMAT = (
    "%(asctime)s  %(levelname)-8s  [%(request_id)s]  %(name)s  %(funcName)s:%(lineno)d"
    "  —  %(message)s"
)
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ─────────────────────────────────────────────────────────────────────────────
# Public configure function
# ─────────────────────────────────────────────────────────────────────────────

def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """
    Configure the root logger for the application.

    Args:
        level: Logging level string — DEBUG | INFO | WARNING | ERROR | CRITICAL
        fmt:   Output format — 'json' (production) | 'text' (development)

    This function is idempotent — safe to call multiple times.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Build the handler
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())

    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        formatter = logging.Formatter(fmt=_TEXT_FORMAT, datefmt=_DATE_FORMAT)
        handler.setFormatter(formatter)

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any existing handlers to avoid duplicate output
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy_logger in ("werkzeug", "urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured",
        extra={"level": level, "format": fmt},
    )