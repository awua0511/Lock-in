"""SQLite connection initialization and pre-migration backup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from lock_in.storage.migrations import MIGRATIONS, run_migrations

DATABASE_FILENAME = "lock-in.sqlite3"
BACKUP_FILENAME = "lock-in.pre-migration.backup.sqlite3"


def database_path(data_directory: Path) -> Path:
    return data_directory / DATABASE_FILENAME


def open_database(path: Path) -> sqlite3.Connection:
    """Open, recover, migrate, and return a connection owned by one thread."""

    path.parent.mkdir(parents=True, exist_ok=True)
    existed_with_data = path.exists() and path.stat().st_size > 0
    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    try:
        current_version = _current_version(connection)
        target_version = MIGRATIONS[-1].version if MIGRATIONS else 0
        if existed_with_data and current_version < target_version:
            _write_backup(connection, path.with_name(BACKUP_FILENAME))
        run_migrations(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def _current_version(connection: sqlite3.Connection) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0])


def _write_backup(connection: sqlite3.Connection, backup_path: Path) -> None:
    backup = sqlite3.connect(backup_path)
    try:
        connection.backup(backup)
    finally:
        backup.close()
