"""Privacy-safe rotating application logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from lock_in.app.config import LOG_BACKUP_COUNT, LOG_FILENAME, LOG_MAX_BYTES

SAFE_LOG_FIELDS = frozenset(
    {
        "component",
        "event_kind",
        "exception_type",
        "operation",
        "pid",
        "state",
        "thread_name",
    }
)
SAFE_LOG_CODES = frozenset(
    {
        "application_event",
        "application_started",
        "application_stopped",
        "component_failed",
        "component_started",
        "component_stopped",
        "duplicate_start_rejected",
        "event_handler_failed",
    }
)


def configure_application_logging(directory: Path) -> logging.Logger:
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("lock_in.application")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing_handler in logger.handlers:
        existing_handler.close()
    logger.handlers.clear()
    handler = RotatingFileHandler(
        directory / LOG_FILENAME,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def safe_log(
    logger: logging.Logger,
    level: int,
    code: str,
    **fields: str | int,
) -> None:
    """Log a stable code and allowlisted metadata, never arbitrary content."""

    if code not in SAFE_LOG_CODES:
        raise ValueError(f"unknown log code: {code}")
    unsupported = fields.keys() - SAFE_LOG_FIELDS
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ValueError(f"unsafe log fields: {names}")
    suffix = " ".join(f"{name}={fields[name]}" for name in sorted(fields))
    logger.log(level, "%s%s", code, f" {suffix}" if suffix else "")
