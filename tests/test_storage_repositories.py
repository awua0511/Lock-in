from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

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
from lock_in.storage.repositories import Repositories
from lock_in.storage.worker import DatabaseWorker


def _schedule() -> Schedule:
    return Schedule(
        id="schedule-1",
        name="Afternoon focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="America/New_York",
        recurrences=(
            Recurrence(
                id="once-1",
                kind=RecurrenceKind.ONCE,
                occurrence_date=date(2026, 9, 18),
            ),
            Recurrence(
                id="weekly-1",
                kind=RecurrenceKind.WEEKLY,
                weekday=0,
            ),
        ),
    )


def _application() -> ApplicationAllowlistEntry:
    return ApplicationAllowlistEntry(
        id="app-1",
        schedule_id="schedule-1",
        identity=ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Microsoft Word",
            executable_path=r"C:\Program Files\Microsoft Office\WINWORD.EXE",
        ),
    )


def test_configuration_survives_worker_restart(tmp_path: Path) -> None:
    path = tmp_path / "lock-in.sqlite3"
    schedule = _schedule()
    application = _application()
    website = WebsiteAllowlistEntry(
        id="site-1", schedule_id=schedule.id, domain="GitHub.com"
    )
    settings = AppSettings(
        review_time=time(21, 15),
        history_retention_days=120,
        follow_up_seconds=420,
    )

    first = DatabaseWorker(path)
    first.start()
    repositories = Repositories.create(first)
    repositories.schedules.save(schedule).result(timeout=2)
    repositories.allowlist.save_application(application).result(timeout=2)
    repositories.allowlist.save_website(website).result(timeout=2)
    repositories.settings.save(settings).result(timeout=2)
    first.stop(2)

    second = DatabaseWorker(path)
    second.start()
    repositories = Repositories.create(second)
    try:
        assert repositories.schedules.get(schedule.id).result(timeout=2) == schedule
        assert repositories.allowlist.list_applications().result(timeout=2) == (
            application,
        )
        assert repositories.allowlist.list_websites().result(timeout=2) == (
            WebsiteAllowlistEntry(
                id="site-1", schedule_id=schedule.id, domain="github.com"
            ),
        )
        assert repositories.settings.load().result(timeout=2) == settings
    finally:
        second.stop(2)


def test_clear_history_preserves_configuration(tmp_path: Path) -> None:
    worker = DatabaseWorker(tmp_path / "lock-in.sqlite3")
    worker.start()
    repositories = Repositories.create(worker)
    schedule = _schedule()
    application = _application()
    website = WebsiteAllowlistEntry(
        id="site-1", schedule_id=schedule.id, domain="github.com"
    )
    settings = AppSettings(history_retention_days=45)
    repositories.schedules.save(schedule).result(timeout=2)
    repositories.allowlist.save_application(application).result(timeout=2)
    repositories.allowlist.save_website(website).result(timeout=2)
    repositories.settings.save(settings).result(timeout=2)

    session = FocusSession(
        id="session-1",
        schedule_id=schedule.id,
        started_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC),
    )
    event = AttentionEvent(
        id="event-1",
        focus_session_id=session.id,
        occurred_at=datetime(2026, 9, 18, 17, 5, tzinfo=UTC),
        target_type=TargetType.WEBSITE,
        target_key="example.com",
        decision=AttentionDecision.CONTINUE,
        foreground_seconds=60,
    )
    repositories.history.save_session(session).result(timeout=2)
    repositories.history.save_event(event).result(timeout=2)

    result = repositories.history.clear().result(timeout=2)
    try:
        assert result.attention_events == 1
        assert result.focus_sessions == 1
        assert repositories.history.list_sessions().result(timeout=2) == ()
        assert repositories.history.list_events().result(timeout=2) == ()
        assert repositories.schedules.list_all().result(timeout=2) == (schedule,)
        assert repositories.allowlist.list_applications().result(timeout=2) == (
            application,
        )
        assert repositories.allowlist.list_websites().result(timeout=2) == (website,)
        assert repositories.settings.load().result(timeout=2) == settings
    finally:
        worker.stop(2)


def test_concurrent_callers_share_exactly_one_writer_thread(tmp_path: Path) -> None:
    worker = DatabaseWorker(tmp_path / "lock-in.sqlite3")
    worker.start()

    def call_from_thread() -> tuple[int, int]:
        caller = threading.get_ident()
        writer = worker.submit(
            lambda connection: (
                connection.execute("SELECT 1").fetchone(),
                threading.get_ident(),
            )[1]
        ).result(timeout=2)
        return caller, writer

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = tuple(executor.map(lambda _: call_from_thread(), range(32)))
        writer_ids = {writer for _, writer in results}
        caller_ids = {caller for caller, _ in results}
        assert writer_ids == {worker.writer_thread_id}
        assert writer_ids.isdisjoint(caller_ids)
    finally:
        worker.stop(2)


def test_failed_operation_does_not_kill_database_worker(tmp_path: Path) -> None:
    worker = DatabaseWorker(tmp_path / "lock-in.sqlite3")
    worker.start()
    try:
        failed = worker.submit(
            lambda connection: connection.execute("SELECT missing_column")
        )
        with pytest.raises(sqlite3.OperationalError):
            failed.result(timeout=2)
        assert (
            worker.submit(
                lambda connection: connection.execute("SELECT 42").fetchone()[0]
            ).result(timeout=2)
            == 42
        )
    finally:
        worker.stop(2)


def test_only_one_worker_can_own_a_database_path(tmp_path: Path) -> None:
    path = tmp_path / "lock-in.sqlite3"
    first = DatabaseWorker(path)
    second = DatabaseWorker(path)
    first.start()
    try:
        with pytest.raises(RuntimeError, match="active writer"):
            second.start()
    finally:
        first.stop(2)

    replacement = DatabaseWorker(path)
    replacement.start()
    replacement.stop(2)


def test_configuration_deletion_is_explicit_and_preserves_history(
    tmp_path: Path,
) -> None:
    worker = DatabaseWorker(tmp_path / "lock-in.sqlite3")
    worker.start()
    repositories = Repositories.create(worker)
    schedule = _schedule()
    application = _application()
    website = WebsiteAllowlistEntry(
        id="site-1", schedule_id=schedule.id, domain="github.com"
    )
    session = FocusSession(
        id="session-1",
        schedule_id=schedule.id,
        started_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC),
    )
    repositories.schedules.save(schedule).result(timeout=2)
    repositories.allowlist.save_application(application).result(timeout=2)
    repositories.allowlist.save_website(website).result(timeout=2)
    repositories.history.save_session(session).result(timeout=2)

    assert repositories.schedules.delete(schedule.id).result(timeout=2)
    try:
        assert repositories.schedules.list_all().result(timeout=2) == ()
        assert repositories.allowlist.list_applications().result(timeout=2) == ()
        assert repositories.allowlist.list_websites().result(timeout=2) == ()
        retained = repositories.history.list_sessions().result(timeout=2)
        assert retained == (
            FocusSession(
                id=session.id,
                schedule_id=None,
                started_at=session.started_at,
            ),
        )
    finally:
        worker.stop(2)
