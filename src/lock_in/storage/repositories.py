"""Typed repositories backed by the single database worker."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
    AppSettings,
    AttentionDecision,
    AttentionEvent,
    FocusSession,
    Recurrence,
    RecurrenceKind,
    Schedule,
    TargetType,
    WebsiteAllowlistEntry,
)
from lock_in.storage.worker import DatabaseWorker


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


class ScheduleRepository:
    def __init__(self, worker: DatabaseWorker) -> None:
        self._worker = worker

    def save(self, schedule: Schedule) -> Future[Schedule]:
        def operation(connection: sqlite3.Connection) -> Schedule:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO schedules(
                        id, name, start_time, end_time, timezone, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        start_time = excluded.start_time,
                        end_time = excluded.end_time,
                        timezone = excluded.timezone,
                        enabled = excluded.enabled,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        schedule.id,
                        schedule.name,
                        schedule.start_time.isoformat(),
                        schedule.end_time.isoformat(),
                        schedule.timezone,
                        int(schedule.enabled),
                    ),
                )
                connection.execute(
                    "DELETE FROM schedule_recurrences WHERE schedule_id = ?",
                    (schedule.id,),
                )
                connection.executemany(
                    """
                    INSERT INTO schedule_recurrences(
                        id, schedule_id, kind, weekday, occurrence_date
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            recurrence.id,
                            schedule.id,
                            recurrence.kind.value,
                            recurrence.weekday,
                            recurrence.occurrence_date.isoformat()
                            if recurrence.occurrence_date
                            else None,
                        )
                        for recurrence in schedule.recurrences
                    ),
                )
            return schedule

        return self._worker.submit(operation)

    def get(self, schedule_id: str) -> Future[Schedule | None]:
        def operation(connection: sqlite3.Connection) -> Schedule | None:
            row = connection.execute(
                "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
            ).fetchone()
            return _schedule_from_row(connection, row) if row else None

        return self._worker.submit(operation)

    def list_all(self) -> Future[tuple[Schedule, ...]]:
        def operation(connection: sqlite3.Connection) -> tuple[Schedule, ...]:
            rows = connection.execute(
                "SELECT * FROM schedules ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
            return tuple(_schedule_from_row(connection, row) for row in rows)

        return self._worker.submit(operation)

    def delete(self, schedule_id: str) -> Future[bool]:
        def operation(connection: sqlite3.Connection) -> bool:
            with _transaction(connection):
                cursor = connection.execute(
                    "DELETE FROM schedules WHERE id = ?", (schedule_id,)
                )
            return cursor.rowcount > 0

        return self._worker.submit(operation)


def _schedule_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> Schedule:
    recurrence_rows = connection.execute(
        """
        SELECT * FROM schedule_recurrences
        WHERE schedule_id = ?
        ORDER BY kind, COALESCE(occurrence_date, ''), COALESCE(weekday, -1), id
        """,
        (row["id"],),
    ).fetchall()
    recurrences = tuple(
        Recurrence(
            id=item["id"],
            kind=RecurrenceKind(item["kind"]),
            weekday=item["weekday"],
            occurrence_date=date.fromisoformat(item["occurrence_date"])
            if item["occurrence_date"]
            else None,
        )
        for item in recurrence_rows
    )
    return Schedule(
        id=row["id"],
        name=row["name"],
        start_time=time.fromisoformat(row["start_time"]),
        end_time=time.fromisoformat(row["end_time"]),
        timezone=row["timezone"],
        enabled=bool(row["enabled"]),
        recurrences=recurrences,
    )


class AllowlistRepository:
    def __init__(self, worker: DatabaseWorker) -> None:
        self._worker = worker

    def save_application(
        self, entry: ApplicationAllowlistEntry
    ) -> Future[ApplicationAllowlistEntry]:
        def operation(connection: sqlite3.Connection) -> ApplicationAllowlistEntry:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO application_allowlist(
                        id, schedule_id, kind, display_name, executable_path,
                        package_family_name, enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        schedule_id = excluded.schedule_id,
                        kind = excluded.kind,
                        display_name = excluded.display_name,
                        executable_path = excluded.executable_path,
                        package_family_name = excluded.package_family_name,
                        enabled = excluded.enabled
                    """,
                    (
                        entry.id,
                        entry.schedule_id,
                        entry.identity.kind.value,
                        entry.identity.display_name,
                        entry.identity.executable_path,
                        entry.identity.package_family_name,
                        int(entry.enabled),
                    ),
                )
            return entry

        return self._worker.submit(operation)

    def list_applications(self) -> Future[tuple[ApplicationAllowlistEntry, ...]]:
        def operation(
            connection: sqlite3.Connection,
        ) -> tuple[ApplicationAllowlistEntry, ...]:
            rows = connection.execute(
                """
                SELECT * FROM application_allowlist
                ORDER BY display_name COLLATE NOCASE, id
                """
            ).fetchall()
            return tuple(
                ApplicationAllowlistEntry(
                    id=row["id"],
                    schedule_id=row["schedule_id"],
                    enabled=bool(row["enabled"]),
                    identity=ApplicationIdentity(
                        kind=ApplicationKind(row["kind"]),
                        display_name=row["display_name"],
                        executable_path=row["executable_path"],
                        package_family_name=row["package_family_name"],
                    ),
                )
                for row in rows
            )

        return self._worker.submit(operation)

    def delete_application(self, entry_id: str) -> Future[bool]:
        return self._delete("application_allowlist", entry_id)

    def save_website(
        self, entry: WebsiteAllowlistEntry
    ) -> Future[WebsiteAllowlistEntry]:
        def operation(connection: sqlite3.Connection) -> WebsiteAllowlistEntry:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO website_allowlist(
                        id, schedule_id, domain, include_subdomains, enabled
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        schedule_id = excluded.schedule_id,
                        domain = excluded.domain,
                        include_subdomains = excluded.include_subdomains,
                        enabled = excluded.enabled
                    """,
                    (
                        entry.id,
                        entry.schedule_id,
                        entry.domain,
                        int(entry.include_subdomains),
                        int(entry.enabled),
                    ),
                )
            return entry

        return self._worker.submit(operation)

    def list_websites(self) -> Future[tuple[WebsiteAllowlistEntry, ...]]:
        def operation(
            connection: sqlite3.Connection,
        ) -> tuple[WebsiteAllowlistEntry, ...]:
            rows = connection.execute(
                "SELECT * FROM website_allowlist ORDER BY domain, id"
            ).fetchall()
            return tuple(
                WebsiteAllowlistEntry(
                    id=row["id"],
                    schedule_id=row["schedule_id"],
                    domain=row["domain"],
                    include_subdomains=bool(row["include_subdomains"]),
                    enabled=bool(row["enabled"]),
                )
                for row in rows
            )

        return self._worker.submit(operation)

    def delete_website(self, entry_id: str) -> Future[bool]:
        return self._delete("website_allowlist", entry_id)

    def _delete(self, table: str, entry_id: str) -> Future[bool]:
        statements = {
            "application_allowlist": "DELETE FROM application_allowlist WHERE id = ?",
            "website_allowlist": "DELETE FROM website_allowlist WHERE id = ?",
        }
        if table not in statements:
            raise ValueError("unsupported allowlist table")
        statement = statements[table]

        def operation(connection: sqlite3.Connection) -> bool:
            with _transaction(connection):
                cursor = connection.execute(statement, (entry_id,))
            return cursor.rowcount > 0

        return self._worker.submit(operation)


class SettingsRepository:
    def __init__(self, worker: DatabaseWorker) -> None:
        self._worker = worker

    def save(self, settings: AppSettings) -> Future[AppSettings]:
        def operation(connection: sqlite3.Connection) -> AppSettings:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO app_settings(
                        profile, review_time, history_retention_days,
                        follow_up_seconds
                    ) VALUES ('default', ?, ?, ?)
                    ON CONFLICT(profile) DO UPDATE SET
                        review_time = excluded.review_time,
                        history_retention_days = excluded.history_retention_days,
                        follow_up_seconds = excluded.follow_up_seconds
                    """,
                    (
                        settings.review_time.isoformat(),
                        settings.history_retention_days,
                        settings.follow_up_seconds,
                    ),
                )
            return settings

        return self._worker.submit(operation)

    def load(self) -> Future[AppSettings]:
        def operation(connection: sqlite3.Connection) -> AppSettings:
            row = connection.execute(
                "SELECT * FROM app_settings WHERE profile = 'default'"
            ).fetchone()
            if row is None:
                return AppSettings()
            return AppSettings(
                review_time=time.fromisoformat(row["review_time"]),
                history_retention_days=row["history_retention_days"],
                follow_up_seconds=row["follow_up_seconds"],
            )

        return self._worker.submit(operation)

    def reset(self) -> Future[AppSettings]:
        def operation(connection: sqlite3.Connection) -> AppSettings:
            with _transaction(connection):
                connection.execute("DELETE FROM app_settings WHERE profile = 'default'")
            return AppSettings()

        return self._worker.submit(operation)


@dataclass(frozen=True, slots=True)
class HistoryClearResult:
    attention_events: int
    focus_sessions: int


class HistoryRepository:
    def __init__(self, worker: DatabaseWorker) -> None:
        self._worker = worker

    def save_session(self, session: FocusSession) -> Future[FocusSession]:
        def operation(connection: sqlite3.Connection) -> FocusSession:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO focus_sessions(
                        id, schedule_id, started_at, ended_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        schedule_id = excluded.schedule_id,
                        started_at = excluded.started_at,
                        ended_at = excluded.ended_at
                    """,
                    (
                        session.id,
                        session.schedule_id,
                        session.started_at.astimezone(UTC).isoformat(),
                        session.ended_at.astimezone(UTC).isoformat()
                        if session.ended_at
                        else None,
                    ),
                )
            return session

        return self._worker.submit(operation)

    def save_event(self, event: AttentionEvent) -> Future[AttentionEvent]:
        def operation(connection: sqlite3.Connection) -> AttentionEvent:
            with _transaction(connection):
                connection.execute(
                    """
                    INSERT INTO attention_events(
                        id, focus_session_id, occurred_at, target_type,
                        target_key, decision, foreground_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        focus_session_id = excluded.focus_session_id,
                        occurred_at = excluded.occurred_at,
                        target_type = excluded.target_type,
                        target_key = excluded.target_key,
                        decision = excluded.decision,
                        foreground_seconds = excluded.foreground_seconds
                    """,
                    (
                        event.id,
                        event.focus_session_id,
                        event.occurred_at.astimezone(UTC).isoformat(),
                        event.target_type.value,
                        event.target_key,
                        event.decision.value,
                        event.foreground_seconds,
                    ),
                )
            return event

        return self._worker.submit(operation)

    def list_sessions(self) -> Future[tuple[FocusSession, ...]]:
        def operation(connection: sqlite3.Connection) -> tuple[FocusSession, ...]:
            rows = connection.execute(
                "SELECT * FROM focus_sessions ORDER BY started_at, id"
            ).fetchall()
            return tuple(
                FocusSession(
                    id=row["id"],
                    schedule_id=row["schedule_id"],
                    started_at=datetime.fromisoformat(row["started_at"]),
                    ended_at=datetime.fromisoformat(row["ended_at"])
                    if row["ended_at"]
                    else None,
                )
                for row in rows
            )

        return self._worker.submit(operation)

    def list_events(self) -> Future[tuple[AttentionEvent, ...]]:
        def operation(connection: sqlite3.Connection) -> tuple[AttentionEvent, ...]:
            rows = connection.execute(
                "SELECT * FROM attention_events ORDER BY occurred_at, id"
            ).fetchall()
            return tuple(
                AttentionEvent(
                    id=row["id"],
                    focus_session_id=row["focus_session_id"],
                    occurred_at=datetime.fromisoformat(row["occurred_at"]),
                    target_type=TargetType(row["target_type"]),
                    target_key=row["target_key"],
                    decision=AttentionDecision(row["decision"]),
                    foreground_seconds=row["foreground_seconds"],
                )
                for row in rows
            )

        return self._worker.submit(operation)

    def clear(self) -> Future[HistoryClearResult]:
        def operation(connection: sqlite3.Connection) -> HistoryClearResult:
            with _transaction(connection):
                events = connection.execute("DELETE FROM attention_events").rowcount
                sessions = connection.execute("DELETE FROM focus_sessions").rowcount
            return HistoryClearResult(events, sessions)

        return self._worker.submit(operation)


@dataclass(frozen=True, slots=True)
class Repositories:
    schedules: ScheduleRepository
    allowlist: AllowlistRepository
    settings: SettingsRepository
    history: HistoryRepository

    @classmethod
    def create(cls, worker: DatabaseWorker) -> Repositories:
        return cls(
            schedules=ScheduleRepository(worker),
            allowlist=AllowlistRepository(worker),
            settings=SettingsRepository(worker),
            history=HistoryRepository(worker),
        )
