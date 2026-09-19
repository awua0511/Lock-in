"""Read-only schema inspection for local acceptance and support."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lock_in.app.config import application_data_directory
from lock_in.storage.database import database_path


def inspect_database(path: Path, *, include_counts: bool = False) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    # Acceptance runs after Lock-In exits, so immutable mode is safe and avoids
    # creating SQLite lock or shared-memory files beside the database.
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()
        ]
        migrations = [
            {"version": row[0], "name": row[1]}
            for row in connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        result: dict[str, Any] = {"migrations": migrations, "tables": tables}
        if include_counts:
            count_tables = (
                "schedules",
                "application_allowlist",
                "focus_sessions",
                "attention_events",
            )
            result["counts"] = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in count_tables
            }
        return result
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect only the Lock-In database schema and migration versions."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=database_path(application_data_directory()),
    )
    parser.add_argument(
        "--include-counts",
        action="store_true",
        help="Include privacy-safe row counts for Milestone 3 acceptance.",
    )
    args = parser.parse_args(argv)
    try:
        result = inspect_database(args.database, include_counts=args.include_counts)
    except FileNotFoundError:
        print(
            f"database not found: {args.database}. Start Lock-In once, then Exit.",
            file=sys.stderr,
        )
        return 1
    except sqlite3.DatabaseError as error:
        print(f"database inspection failed: {type(error).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
