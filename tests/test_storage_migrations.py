from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lock_in.storage.database import BACKUP_FILENAME, open_database
from lock_in.storage.inspect import inspect_database
from lock_in.storage.migrations import MIGRATIONS, Migration, run_migrations

EXPECTED_TABLES = {
    "app_settings",
    "application_allowlist",
    "attention_events",
    "focus_sessions",
    "schedule_recurrences",
    "schedules",
    "schema_migrations",
    "website_allowlist",
}


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def test_empty_profile_migrates_to_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "profile.sqlite3"
    connection = open_database(path)
    try:
        assert _tables(connection) == EXPECTED_TABLES
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in versions] == [1, 2]
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        connection.close()
    inspection = inspect_database(path)
    assert inspection["migrations"] == [
        {"version": 1, "name": "configuration"},
        {"version": 2, "name": "history"},
    ]
    assert set(inspection["tables"]) == EXPECTED_TABLES
    counted = inspect_database(path, include_counts=True)
    assert counted["counts"] == {
        "schedules": 0,
        "application_allowlist": 0,
        "focus_sessions": 0,
        "attention_events": 0,
    }


@pytest.mark.parametrize("failed_version", [1, 2])
def test_each_migration_rolls_back_and_can_resume(
    tmp_path: Path, failed_version: int
) -> None:
    path = tmp_path / f"interrupted-{failed_version}.sqlite3"
    connection = _connect(path)
    try:
        if failed_version == 2:
            run_migrations(connection, MIGRATIONS[:1])
        original = MIGRATIONS[failed_version - 1]
        failed = Migration(
            version=original.version,
            name=original.name,
            statements=original.statements + ("THIS IS NOT VALID SQL",),
        )
        candidates = MIGRATIONS[: failed_version - 1] + (failed,)

        with pytest.raises(sqlite3.OperationalError):
            run_migrations(connection, candidates)

        applied = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        expected_applied = [(1,)] if failed_version == 2 else []
        assert applied == expected_applied
        failed_table = "focus_sessions" if failed_version == 2 else "schedules"
        assert failed_table not in _tables(connection)
    finally:
        connection.close()

    recovered = _connect(path)
    try:
        run_migrations(recovered)
        assert _tables(recovered) == EXPECTED_TABLES
    finally:
        recovered.close()


@pytest.mark.parametrize("interrupted_version", [1, 2])
def test_each_uncommitted_migration_recovers_after_reconnect(
    tmp_path: Path, interrupted_version: int
) -> None:
    path = tmp_path / f"crash-{interrupted_version}.sqlite3"
    connection = _connect(path)
    if interrupted_version == 2:
        run_migrations(connection, MIGRATIONS[:1])
    else:
        run_migrations(connection, ())
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(MIGRATIONS[interrupted_version - 1].statements[0])
    connection.close()

    recovered = _connect(path)
    try:
        run_migrations(recovered)
        assert _tables(recovered) == EXPECTED_TABLES
        assert recovered.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]
    finally:
        recovered.close()


def test_existing_profile_is_backed_up_before_upgrade(tmp_path: Path) -> None:
    path = tmp_path / "profile.sqlite3"
    connection = _connect(path)
    run_migrations(connection, MIGRATIONS[:1])
    connection.execute(
        """
        INSERT INTO schedules(
            id, name, start_time, end_time, timezone, enabled
        ) VALUES ('saved', 'Saved schedule', '13:00:00', '13:40:00', 'UTC', 1)
        """
    )
    connection.close()

    upgraded = open_database(path)
    upgraded.close()

    backup_path = tmp_path / BACKUP_FILENAME
    assert backup_path.exists()
    backup = sqlite3.connect(backup_path)
    try:
        assert backup.execute(
            "SELECT name FROM schedules WHERE id = 'saved'"
        ).fetchone() == ("Saved schedule",)
        assert backup.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,)]
        assert "focus_sessions" not in _tables(backup)
    finally:
        backup.close()
