"""Central constants and filesystem locations for the desktop application."""

from __future__ import annotations

import os
from pathlib import Path

APPLICATION_NAME = "Lock-In"
ORGANIZATION_NAME = "Lock-In"
APPLICATION_VERSION = "0.1.0"
LOG_FILENAME = "lock-in.log"
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3
SHUTDOWN_TIMEOUT_SECONDS = 2.0


def application_data_directory() -> Path:
    """Return the per-user application data directory without creating it."""

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "LockIn"
    return Path.home() / "AppData" / "Local" / "LockIn"


def log_directory() -> Path:
    return application_data_directory() / "Logs"
