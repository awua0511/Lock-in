import sqlite3
from datetime import datetime

import pytest

from lock_in.domain.models import AppSettings
from lock_in.storage.database import BACKUP_FILENAME, open_database
from lock_in.storage.migrations import MIGRATIONS, Migration, run_migrations
from lock_in.storage.reviews import ReviewRepository
from lock_in.storage.worker import DatabaseWorker


def legacy_profile(path):
    connection = sqlite3.connect(path, isolation_level=None)
    run_migrations(connection, MIGRATIONS[:3])
    connection.execute("DROP TABLE review_deliveries")
    connection.execute(
        "CREATE TABLE review_deliveries (local_day TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL)"
    )
    rows = [
        ("2026-09-26", "2026-09-28T08:00:00-04:00", "catch_up", "submitted_to_windows"),
        ("2026-09-27", "2026-09-28T09:00:00-04:00", "catch_up", "reserved"),
        ("2026-09-25", "2026-09-27T09:00:00-04:00", "expired_history", "skipped"),
    ]
    connection.executemany("INSERT INTO review_deliveries VALUES (?, ?, ?, ?)", rows)
    connection.execute(
        "INSERT INTO app_settings VALUES ('default', '20:00:00', 90, 300)"
    )
    return connection, rows


def test_legacy_v3_upgrade_preserves_receipts_settings_backup_and_daily_limit(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    connection, rows = legacy_profile(path)
    connection.close()
    worker = DatabaseWorker(path)
    worker.start()
    try:
        repository = ReviewRepository(worker)
        now = datetime.fromisoformat("2026-09-28T21:00:00-04:00")
        assert repository.check_due(now, AppSettings()).result(3) is None
        assert repository.load(now.date()).result(3).day == now.date()
    finally:
        worker.stop(3)
    connection = open_database(path)
    try:
        for row in rows:
            actual = connection.execute(
                "SELECT local_day, attempted_at, reason, status FROM review_deliveries WHERE local_day = ?",
                (row[0],),
            ).fetchone()
            assert tuple(actual) == row
        assert (
            connection.execute("SELECT follow_up_seconds FROM app_settings").fetchone()[
                0
            ]
            == 300
        )
        assert (
            connection.execute(
                "SELECT local_day FROM review_deliveries WHERE delivery_day = '2026-09-28'"
            ).fetchone()[0]
            == "2026-09-26"
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()
    backup = sqlite3.connect(tmp_path / BACKUP_FILENAME)
    try:
        assert "delivery_day" not in {
            r[1] for r in backup.execute("PRAGMA table_info(review_deliveries)")
        }
        assert (
            backup.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
            == 3
        )
    finally:
        backup.close()


def test_modern_v3_and_repeated_start_keep_existing_delivery_days(tmp_path):
    path = tmp_path / "modern.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    run_migrations(connection, MIGRATIONS[:3])
    row = (
        "2026-09-27",
        "2026-09-28T08:00:00-04:00",
        "catch_up",
        "reserved",
        "2026-09-28",
    )
    connection.execute("INSERT INTO review_deliveries VALUES (?, ?, ?, ?, ?)", row)
    connection.close()
    for _ in range(2):
        connection = open_database(path)
        assert (
            tuple(connection.execute("SELECT * FROM review_deliveries").fetchone())
            == row
        )
        assert (
            connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 4
        )
        connection.close()


def test_compatibility_migration_is_atomic_and_retryable(tmp_path):
    connection, rows = legacy_profile(tmp_path / "interrupted.sqlite3")
    original = MIGRATIONS[-1]
    failed = Migration(4, original.name, original.statements + ("INVALID SQL",))
    try:
        with pytest.raises(sqlite3.OperationalError):
            run_migrations(connection, MIGRATIONS[:3] + (failed,))
        assert "delivery_day" not in {
            r[1] for r in connection.execute("PRAGMA table_info(review_deliveries)")
        }
        assert (
            connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[
                0
            ]
            == 3
        )
        assert connection.execute("SELECT count(*) FROM review_deliveries").fetchone()[
            0
        ] == len(rows)
        run_migrations(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO review_deliveries VALUES ('2026-09-29', 'now', 'test', 'reserved', '2026-09-28')"
            )
    finally:
        connection.close()
