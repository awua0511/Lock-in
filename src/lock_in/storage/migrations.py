"""Explicit, atomic SQLite schema migrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        1,
        "configuration",
        (
            """
            CREATE TABLE schedules (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                timezone TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE schedule_recurrences (
                id TEXT PRIMARY KEY,
                schedule_id TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('once', 'weekly')),
                weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
                occurrence_date TEXT,
                CHECK (
                    (kind = 'once' AND occurrence_date IS NOT NULL AND weekday IS NULL)
                    OR
                    (kind = 'weekly' AND weekday IS NOT NULL AND occurrence_date IS NULL)
                )
            )
            """,
            """
            CREATE TABLE application_allowlist (
                id TEXT PRIMARY KEY,
                schedule_id TEXT REFERENCES schedules(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('win32', 'packaged')),
                display_name TEXT NOT NULL,
                executable_path TEXT,
                package_family_name TEXT,
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                CHECK (
                    (kind = 'win32' AND executable_path IS NOT NULL
                        AND package_family_name IS NULL)
                    OR
                    (kind = 'packaged' AND package_family_name IS NOT NULL
                        AND executable_path IS NULL)
                )
            )
            """,
            """
            CREATE TABLE website_allowlist (
                id TEXT PRIMARY KEY,
                schedule_id TEXT REFERENCES schedules(id) ON DELETE CASCADE,
                domain TEXT NOT NULL,
                include_subdomains INTEGER NOT NULL
                    CHECK (include_subdomains IN (0, 1)),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
            )
            """,
            """
            CREATE TABLE app_settings (
                profile TEXT PRIMARY KEY,
                review_time TEXT NOT NULL,
                history_retention_days INTEGER NOT NULL,
                follow_up_seconds INTEGER NOT NULL
            )
            """,
            "CREATE INDEX idx_recurrences_schedule ON schedule_recurrences(schedule_id)",
            """
            CREATE INDEX idx_application_allowlist_schedule
            ON application_allowlist(schedule_id)
            """,
            """
            CREATE UNIQUE INDEX idx_website_allowlist_global_domain
            ON website_allowlist(domain) WHERE schedule_id IS NULL
            """,
            """
            CREATE UNIQUE INDEX idx_website_allowlist_schedule_domain
            ON website_allowlist(schedule_id, domain) WHERE schedule_id IS NOT NULL
            """,
        ),
    ),
    Migration(
        2,
        "history",
        (
            """
            CREATE TABLE focus_sessions (
                id TEXT PRIMARY KEY,
                schedule_id TEXT REFERENCES schedules(id) ON DELETE SET NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT
            )
            """,
            """
            CREATE TABLE attention_events (
                id TEXT PRIMARY KEY,
                focus_session_id TEXT NOT NULL
                    REFERENCES focus_sessions(id) ON DELETE CASCADE,
                occurred_at TEXT NOT NULL,
                target_type TEXT NOT NULL
                    CHECK (target_type IN ('application', 'website')),
                target_key TEXT NOT NULL,
                decision TEXT NOT NULL
                    CHECK (decision IN ('prompt_shown', 'return', 'continue')),
                foreground_seconds INTEGER NOT NULL DEFAULT 0
                    CHECK (foreground_seconds >= 0)
            )
            """,
            "CREATE INDEX idx_attention_occurred ON attention_events(occurred_at)",
            "CREATE INDEX idx_attention_session ON attention_events(focus_session_id)",
        ),
    ),
)


def run_migrations(
    connection: sqlite3.Connection,
    migrations: tuple[Migration, ...] = MIGRATIONS,
) -> int:
    """Apply missing migrations, committing each version independently."""

    versions = tuple(migration.version for migration in migrations)
    if versions != tuple(range(1, len(migrations) + 1)):
        raise ValueError("migration versions must be consecutive and start at one")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied_rows = connection.execute(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row[0]): str(row[1]) for row in applied_rows}
    unknown = set(applied) - set(versions)
    if unknown:
        raise RuntimeError("database contains unsupported migration versions")
    applied_versions = tuple(sorted(applied))
    if applied_versions != tuple(range(1, len(applied_versions) + 1)):
        raise RuntimeError("database migration history is not a valid prefix")
    for migration in migrations:
        existing_name = applied.get(migration.version)
        if existing_name is not None and existing_name != migration.name:
            raise RuntimeError("database migration name does not match application")
        if existing_name is not None:
            continue
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
    return migrations[-1].version if migrations else 0
