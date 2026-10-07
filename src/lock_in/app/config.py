"""Central constants and filesystem locations for the desktop application."""

from __future__ import annotations

import os
from pathlib import Path

APPLICATION_NAME = "Lock-In"
ORGANIZATION_NAME = "Lock-In"
APPLICATION_VERSION = "0.1.1"
LOG_FILENAME = "lock-in.log"
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3
SHUTDOWN_TIMEOUT_SECONDS = 2.0
USER_EXIT_MARKER = "user-requested-exit.marker"


def application_data_directory() -> Path:
    """Return the per-user application data directory without creating it."""

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "LockIn"
    return Path.home() / "AppData" / "Local" / "LockIn"


def log_directory() -> Path:
    return application_data_directory() / "Logs"


def user_exit_marker_path() -> Path:
    return application_data_directory() / USER_EXIT_MARKER


def user_requested_exit() -> bool:
    return user_exit_marker_path().is_file()


def mark_user_requested_exit() -> None:
    marker = user_exit_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("user requested exit\n", encoding="utf-8")


def clear_user_requested_exit() -> None:
    user_exit_marker_path().unlink(missing_ok=True)
