from __future__ import annotations

import logging
import queue
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone

import pytest

from lock_in.app.review_service import ReviewCompletion, ReviewService
from lock_in.domain.models import (
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
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)
from lock_in.reviews.models import UsageRecord
from lock_in.reviews.usage import UsageTracker
from lock_in.rules.application_policy import FocusConfiguration
from lock_in.storage.repositories import Repositories
from lock_in.storage.reviews import ReviewRepository
from lock_in.storage.worker import DatabaseWorker

DAY = date(2026, 9, 28)
NOW = datetime(2026, 9, 28, 13, tzinfo=UTC)


def schedule(**changes):
    value = Schedule(
        "Work",
        time(13),
        time(14),
        "UTC",
        (Recurrence(RecurrenceKind.WEEKLY, weekday=0),),
    )
    return replace(value, **changes)


def observation(path=r"C:\Games\Steam.exe", hwnd=20, pid=200):
    return ForegroundObservation(
        1, NOW.isoformat(), 0, hwnd, pid, "App", path, ResolutionStatus.IDENTIFIED
    )


def tracker():
    result = UsageTracker(999)
    result.configuration = FocusConfiguration(schedules=(schedule(),))
    result.observe(observation())
    result.advance(NOW, 0)
    return result


@pytest.fixture
def database(tmp_path):
    worker = DatabaseWorker(tmp_path / "review.sqlite3")
    worker.start()
    yield worker, Repositories.create(worker), ReviewRepository(worker)
    worker.stop(3)


def test_usage_union_clock_changes_and_unknown_browser():
    usage = tracker()
    usage.configuration = replace(
        usage.configuration, schedules=(schedule(), schedule())
    )
    result = usage.advance(NOW + timedelta(hours=5), 2000)
    assert sum(row.scheduled_ms for row in result) == 2000
    assert sum(row.outside_ms for row in result) == 2000
    usage.advance(NOW, 2000)
    usage.observe(observation(r"C:\Chrome\chrome.exe"))
    assert sum(row.outside_ms for row in usage.advance(NOW, 3000)) == 0
    usage.website("youtube.com", 20)
    assert sum(row.outside_ms for row in usage.advance(NOW, 4000)) == 1000
    usage.website(None, 20)
    assert sum(row.outside_ms for row in usage.advance(NOW, 5000)) == 0
    usage.website("youtube.com", 21)  # A different window cannot set the domain.
    assert sum(row.outside_ms for row in usage.advance(NOW, 6000)) == 0


def test_usage_allowlisted_site_own_prompt_sleep_and_long_gap():
    usage = tracker()
    usage.configuration = replace(
        usage.configuration, websites=(WebsiteAllowlistEntry("example.com"),)
    )
    usage.observe(observation(r"C:\Chrome\chrome.exe"))
    usage.website("docs.example.com", 20)
    assert sum(row.outside_ms for row in usage.advance(NOW, 1000)) == 0
    usage.website("example.com.evil.test", 20)
    assert sum(row.outside_ms for row in usage.advance(NOW, 2000)) == 1000
    usage.observe(observation(pid=999))
    assert sum(row.outside_ms for row in usage.advance(NOW, 3000)) == 0
    usage.availability(False)
    assert usage.advance(NOW, 60000) == ()
    usage.availability(True)
    assert usage.advance(NOW, 61000) == ()
    assert usage.advance(NOW, 62000) == ()  # Requires fresh foreground.
    usage.observe(observation())
    assert usage.advance(NOW, 80000) == ()  # Unknown long delay excluded.
    assert sum(row.outside_ms for row in usage.advance(NOW, 81000)) == 1000
    assert usage.advance(NOW, 80500) == ()
    assert sum(row.outside_ms for row in usage.advance(NOW, 82000)) == 1000


def test_usage_splits_midnight_and_stops_at_schedule_end():
    usage = UsageTracker(999)
    usage.configuration = FocusConfiguration(
        schedules=(schedule(start_time=time(23), end_time=time(0, 0, 1)),)
    )
    usage.observe(observation())
    before = NOW.replace(hour=23, minute=59, second=59, microsecond=500000)
    usage.advance(before, 0)
    records = usage.advance(before + timedelta(seconds=2), 2000)
    assert sum(r.scheduled_ms for r in records if r.local_day == DAY) == 500
    assert (
        sum(r.scheduled_ms for r in records if r.local_day == DAY + timedelta(days=1))
        == 1000
    )


def test_daily_aggregate_separates_entries_followups_and_idempotent_usage(database):
    _, repos, reviews = database
    session = FocusSession(NOW)
    repos.history.save_session(session).result()
    for kind, decision in [
        ("entry", AttentionDecision.PROMPT_SHOWN),
        ("entry", AttentionDecision.CONTINUE),
        ("follow_up", AttentionDecision.PROMPT_SHOWN),
        ("follow_up", AttentionDecision.CONTINUE),
    ]:
        repos.history.save_event(
            AttentionEvent(
                session.id,
                NOW,
                TargetType.WEBSITE,
                "youtube.com",
                decision,
                30,
                prompt_kind=kind,
            )
        ).result()
    record = UsageRecord(DAY, NOW, 60000, 30000)
    reviews.save_usage((record,)).result()
    reviews.save_usage((record,)).result()
    result = reviews.load(DAY).result()
    assert (result.entries, result.follow_ups, result.continues, result.returns) == (
        1,
        1,
        2,
        0,
    )
    assert (result.scheduled_ms, result.outside_ms, result.event_count) == (
        60000,
        30000,
        4,
    )
    assert len(result.details) == 4


def test_notification_once_per_local_day_persists_across_repository_restart(database):
    worker, _, reviews = database
    settings = AppSettings()
    assert reviews.check_due(NOW, settings).result() is None
    due = NOW.replace(hour=20)
    notice = reviews.check_due(due, settings).result()
    assert notice.day == DAY
    again = ReviewRepository(worker)
    assert again.check_due(due + timedelta(seconds=30), settings).result() is None
    assert (
        again.check_due(
            due.replace(tzinfo=timezone(timedelta(hours=-7))), settings
        ).result()
        is None
    )
    assert (
        "zone"
        in worker.submit(
            lambda c: dict(c.execute("SELECT key, value FROM review_state"))
        ).result()
    )
    assert (
        "last_clock_change"
        in worker.submit(
            lambda c: dict(c.execute("SELECT key, value FROM review_state"))
        ).result()
    )


def test_catch_up_coalesces_multiple_missed_days_and_handles_clock_rollback(database):
    worker, _, reviews = database
    settings = AppSettings()
    reviews.check_due(NOW, settings).result()
    resumed = NOW + timedelta(days=3)
    notice = reviews.check_due(resumed, settings).result()
    assert notice.day == DAY + timedelta(days=2)
    assert notice.reason == "catch_up"
    assert reviews.check_due(resumed + timedelta(seconds=15), settings).result() is None
    state = worker.submit(
        lambda c: dict(c.execute("SELECT key, value FROM review_state"))
    ).result()
    assert "last_coalesced_gap" in state
    # Catch-up consumes today's delivery slot; no second notification tonight.
    assert reviews.check_due(resumed.replace(hour=20), settings).result() is None
    assert (
        reviews.load(resumed.date()).result().delivery_status
        == "daily_delivery_limit: skipped"
    )
    assert reviews.check_due(resumed.replace(hour=19), settings).result() is None
    assert reviews.check_due(resumed.replace(hour=20), settings).result() is None


def test_retention_preserves_configuration_and_delivery_ledger(database):
    worker, repos, reviews = database
    work = schedule()
    repos.schedules.save(work).result()
    repos.allowlist.save_website(WebsiteAllowlistEntry("example.com")).result()
    old = NOW - timedelta(days=10)
    session = FocusSession(old, ended_at=old + timedelta(hours=1))
    repos.history.save_session(session).result()
    repos.history.save_event(
        AttentionEvent(
            session.id,
            old,
            TargetType.WEBSITE,
            "example.com",
            AttentionDecision.CONTINUE,
        )
    ).result()
    reviews.save_usage((UsageRecord(old.date(), old, 1000, 1000),)).result()
    reviews.check_due(old.replace(hour=20), AppSettings()).result()
    reviews.check_due(NOW, AppSettings(history_retention_days=3)).result()
    assert repos.history.list_events().result() == ()
    assert repos.history.list_sessions().result() == ()
    assert reviews.load(old.date()).result().scheduled_ms == 0
    assert repos.schedules.get(work.id).result() == work
    assert len(repos.allowlist.list_websites().result()) == 1
    assert (
        worker.submit(
            lambda c: c.execute("SELECT COUNT(*) FROM review_deliveries").fetchone()[0]
        ).result()
        == 2
    )
    repos.history.clear().result()
    assert reviews.check_due(old.replace(hour=20), AppSettings()).result() is None


def test_event_local_date_is_not_regrouped_as_utc(database):
    _, repos, reviews = database
    local = NOW.replace(hour=0, tzinfo=timezone(timedelta(hours=9)))
    session = FocusSession(local)
    repos.history.save_session(session).result()
    repos.history.save_event(
        AttentionEvent(
            session.id,
            local,
            TargetType.APPLICATION,
            r"C:\App.exe",
            AttentionDecision.CONTINUE,
        )
    ).result()
    assert reviews.load(DAY).result().continues == 1
    assert reviews.load(DAY - timedelta(days=1)).result().continues == 0


class ReviewUi:
    def __init__(self):
        self.views = []
        self.notifications = []
        self.errors = []

    def update_review(self, value):
        self.views.append(value)

    def show_review_notification(self, value):
        self.notifications.append(value)

    def report_operation_error(self, value):
        self.errors.append(value)


def review_service(database):
    worker, _, repository = database
    ui = ReviewUi()
    events = queue.SimpleQueue()
    clock = [NOW, 0]
    service = ReviewService(
        repository,
        ui,
        logging.getLogger("test.reviews"),
        events.put,
        clock=lambda: clock[0],
        monotonic=lambda: clock[1],
        own_pid=999,
    )

    def drain():
        for _ in range(10):
            worker.submit(lambda _connection: None).result(timeout=2)
            count = 0
            while not events.empty():
                service.complete(events.get_nowait().payload)
                count += 1
            if not count:
                return
        raise AssertionError("Review events did not settle")

    return service, ui, clock, drain


def test_service_flushes_usage_on_view_and_ignores_old_view_results(database):
    service, ui, clock, drain = review_service(database)
    service.update_focus_configuration(FocusConfiguration(schedules=(schedule(),)))
    service.observe_foreground(observation())
    clock[:] = [NOW + timedelta(seconds=2), 2000]
    service.tick(*clock)
    service.request(DAY - timedelta(days=1))
    service.request(DAY)
    drain()
    assert len(ui.views) == 1
    assert ui.views[0].scheduled_ms == 2000
    assert ui.views[0].outside_ms == 2000
    assert ui.errors == []
    service.stop(2)


def test_service_defers_notification_while_locked_and_persists_result(database):
    _, _, repository = database
    service, ui, clock, drain = review_service(database)
    service.tick(*clock)
    drain()
    service.availability(False, 1000)
    clock[:] = [NOW.replace(hour=21), 2000]
    service.tick(*clock)
    drain()
    assert ui.notifications == []
    service.availability(True, 3000)
    clock[1] = 4000
    service.tick(*clock)
    drain()
    assert len(ui.notifications) == 1
    from lock_in.reviews.models import NotificationResult

    service.notification_result(NotificationResult(DAY, "unavailable"))
    drain()
    assert repository.load(DAY).result().delivery_status == "catch_up: unavailable"
    clock[1] = 20000
    service.tick(*clock)
    drain()
    assert len(ui.notifications) == 1
    service.stop(2)


def test_failed_usage_write_retries_without_counting_twice(database, monkeypatch):
    _, _, repository = database
    service, ui, clock, drain = review_service(database)
    original = repository.save_usage
    calls = []

    def fail_once(records):
        calls.append(records)
        if len(calls) == 1:
            failed = Future()
            failed.set_exception(OSError("simulated disk failure"))
            return failed
        return original(records)

    monkeypatch.setattr(repository, "save_usage", fail_once)
    service.update_focus_configuration(FocusConfiguration(schedules=(schedule(),)))
    service.observe_foreground(observation())
    clock[:] = [NOW + timedelta(seconds=1), 1000]
    service.request(DAY)
    drain()
    assert ui.errors == ["review_usage"]
    service.request(DAY)
    drain()
    assert ui.views[-1].outside_ms == 1000
    assert calls[0][0].id == calls[1][0].id
    service.stop(2)


def test_delivery_day_is_rechecked_after_loading_across_midnight(database):
    _, _, reviews = database
    reviews.check_due(NOW.replace(hour=23), AppSettings()).result()
    tomorrow = NOW + timedelta(days=1)
    assert reviews.prepare_delivery(DAY, tomorrow).result()
    assert reviews.check_due(tomorrow.replace(hour=20), AppSettings()).result() is None
    assert (
        reviews.load(tomorrow.date()).result().delivery_status
        == "daily_delivery_limit: skipped"
    )


def test_active_session_is_not_deleted_by_midnight_retention(database):
    _, repos, reviews = database
    active = FocusSession(NOW - timedelta(days=1))
    repos.history.save_session(active).result()
    reviews.check_due(NOW, AppSettings(history_retention_days=1)).result()
    repos.history.save_event(
        AttentionEvent(
            active.id,
            NOW,
            TargetType.WEBSITE,
            "example.com",
            AttentionDecision.CONTINUE,
        )
    ).result()
    assert reviews.load(DAY).result().continues == 1


def test_async_notification_waits_for_unlock_and_moves_delivery_slot(database):
    _, _, reviews = database
    service, ui, clock, drain = review_service(database)
    reviews.check_due(NOW.replace(hour=21), AppSettings()).result()
    service.availability(False, 1000)
    service.complete(ReviewCompletion("notify", reviews.load(DAY).result()))
    assert ui.notifications == []
    clock[:] = [NOW + timedelta(days=1), 2000]
    service.availability(True, 2000)
    service.tick(*clock)
    drain()
    assert len(ui.notifications) == 1
    assert ui.notifications[0].day == DAY
    assert reviews.check_due(clock[0].replace(hour=20), AppSettings()).result() is None
    service.stop(2)


def test_notification_reservation_survives_database_close_and_reopen(tmp_path):
    path = tmp_path / "restart.sqlite3"
    first = DatabaseWorker(path)
    first.start()
    try:
        assert (
            ReviewRepository(first)
            .check_due(NOW.replace(hour=20), AppSettings())
            .result()
        )
    finally:
        first.stop(2)
    restarted = DatabaseWorker(path)
    restarted.start()
    try:
        reviews = ReviewRepository(restarted)
        assert reviews.check_due(NOW.replace(hour=21), AppSettings()).result() is None
        assert reviews.load(DAY).result().delivery_status == "catch_up: reserved"
    finally:
        restarted.stop(2)


def test_retention_does_not_send_empty_expired_catchup_or_restore_old_usage(database):
    _, _, reviews = database
    yesterday = NOW - timedelta(days=1)
    reviews.check_due(yesterday, AppSettings()).result()
    old = UsageRecord(yesterday.date(), yesterday, 20000, 10000)
    reviews.save_usage((old,)).result()
    assert (
        reviews.check_due(NOW, AppSettings(history_retention_days=1)).result() is None
    )
    assert (
        reviews.load(yesterday.date()).result().delivery_status
        == "expired_history: skipped"
    )
    reviews.save_usage((old,)).result()  # A delayed retry must obey the same cutoff.
    assert reviews.load(yesterday.date()).result().scheduled_ms == 0
    assert (
        reviews.check_due(
            NOW.replace(hour=20), AppSettings(history_retention_days=1)
        ).result()
        is not None
    )


def test_interrupted_sessions_can_expire_without_invented_crash_duration(database):
    _, repos, reviews = database
    old = NOW - timedelta(days=10)
    session = FocusSession(old)
    repos.history.save_session(session).result()
    assert repos.history.close_interrupted_sessions().result() == 1
    assert repos.history.list_sessions().result()[0].ended_at == old
    reviews.check_due(NOW, AppSettings(history_retention_days=1)).result()
    assert repos.history.list_sessions().result() == ()
