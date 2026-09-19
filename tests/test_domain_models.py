from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from lock_in.domain.models import (
    ApplicationIdentity,
    ApplicationKind,
    AttentionDecision,
    AttentionEvent,
    FocusSession,
    Recurrence,
    RecurrenceKind,
    Schedule,
    TargetType,
    WebsiteAllowlistEntry,
)


def test_schedule_requires_valid_recurrence_and_local_times() -> None:
    recurrence = Recurrence(
        kind=RecurrenceKind.WEEKLY,
        weekday=0,
    )
    schedule = Schedule(
        name="Deep work",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="America/New_York",
        recurrences=(recurrence,),
    )

    assert schedule.recurrences == (recurrence,)
    with pytest.raises(ValueError, match="occurrence_date"):
        Recurrence(kind=RecurrenceKind.ONCE)
    with pytest.raises(ValueError, match="weekday"):
        Recurrence(kind=RecurrenceKind.WEEKLY, weekday=7)


def test_identity_variants_are_mutually_exclusive() -> None:
    identity = ApplicationIdentity(
        kind=ApplicationKind.WIN32,
        display_name="Word",
        executable_path=r"C:\Program Files\Microsoft Office\WINWORD.EXE",
    )
    assert identity.package_family_name is None

    with pytest.raises(ValueError, match="only executable_path"):
        ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Invalid",
            executable_path=r"C:\invalid.exe",
            package_family_name="invalid_family",
        )


def test_website_entry_normalizes_hostname_but_rejects_urls() -> None:
    entry = WebsiteAllowlistEntry(domain="GitHub.COM.")
    assert entry.domain == "github.com"

    with pytest.raises(ValueError, match="hostname, not a URL"):
        WebsiteAllowlistEntry(domain="https://github.com/path")


def test_history_models_require_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="UTC offset"):
        FocusSession(started_at=datetime(2026, 9, 18, 13, 0))

    session = FocusSession(started_at=datetime(2026, 9, 18, 17, 0, tzinfo=UTC))
    event = AttentionEvent(
        focus_session_id=session.id,
        occurred_at=datetime(2026, 9, 18, 17, 5, tzinfo=UTC),
        target_type=TargetType.APPLICATION,
        target_key="example.exe",
        decision=AttentionDecision.CONTINUE,
        foreground_seconds=30,
    )
    assert event.foreground_seconds == 30


def test_one_time_recurrence_accepts_a_calendar_date() -> None:
    recurrence = Recurrence(
        kind=RecurrenceKind.ONCE,
        occurrence_date=date(2026, 9, 18),
    )
    assert recurrence.weekday is None
