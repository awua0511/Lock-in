from __future__ import annotations

from datetime import UTC, datetime, time

from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
    Recurrence,
    RecurrenceKind,
    Schedule,
)
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)
from lock_in.rules.application_policy import (
    ApplicationFocusPolicy,
    FocusConfiguration,
    PolicyDecision,
    active_schedules_at,
)


def _schedule(
    *,
    schedule_id: str = "schedule-1",
    weekday: int = 0,
    start: time = time(13, 0),
    end: time = time(13, 40),
) -> Schedule:
    return Schedule(
        id=schedule_id,
        name=schedule_id,
        start_time=start,
        end_time=end,
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=weekday),),
    )


def _allowed(
    path: str, schedule_id: str | None = "schedule-1"
) -> ApplicationAllowlistEntry:
    return ApplicationAllowlistEntry(
        schedule_id=schedule_id,
        identity=ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Allowed",
            executable_path=path,
        ),
    )


def _observation(
    sequence: int,
    hwnd: int,
    path: str,
    *,
    pid: int = 200,
) -> ForegroundObservation:
    return ForegroundObservation(
        sequence=sequence,
        observed_at=f"2026-09-14T13:0{sequence}:00+00:00",
        monotonic_ms=sequence * 100,
        hwnd=hwnd,
        pid=pid,
        application_name=path.rsplit("\\", 1)[-1].removesuffix(".exe"),
        executable_path=path,
        status=ResolutionStatus.IDENTIFIED,
    )


def test_schedule_boundaries_and_midnight_crossing() -> None:
    monday = _schedule()
    overnight = _schedule(
        schedule_id="overnight",
        weekday=0,
        start=time(23, 0),
        end=time(1, 0),
    )

    assert (
        active_schedules_at((monday,), datetime(2026, 9, 14, 12, 59, tzinfo=UTC)) == ()
    )
    assert active_schedules_at((monday,), datetime(2026, 9, 14, 13, 0, tzinfo=UTC)) == (
        monday,
    )
    assert (
        active_schedules_at((monday,), datetime(2026, 9, 14, 13, 40, tzinfo=UTC)) == ()
    )
    assert active_schedules_at(
        (overnight,), datetime(2026, 9, 15, 0, 30, tzinfo=UTC)
    ) == (overnight,)
    assert (
        active_schedules_at((overnight,), datetime(2026, 9, 15, 1, 0, tzinfo=UTC)) == ()
    )


def test_overlapping_schedules_use_union_of_scoped_allowlists() -> None:
    first = _schedule(schedule_id="a")
    second = _schedule(schedule_id="b")
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(
        FocusConfiguration((first, second), (_allowed(r"C:\Work\Word.exe", "b"),))
    )

    update = policy.observe(
        _observation(1, 10, r"c:\work\WORD.EXE"),
        datetime(2026, 9, 14, 13, 5, tzinfo=UTC),
    )
    assert update.prompt is None
    assert update.active_schedules == (first, second)


def test_one_prompt_per_entry_continue_then_reentry() -> None:
    schedule = _schedule()
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(
        FocusConfiguration((schedule,), (_allowed(r"C:\Work\Word.exe"),))
    )
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)

    assert policy.observe(_observation(1, 10, r"C:\Work\Word.exe"), now).prompt is None
    first = policy.observe(_observation(2, 20, r"C:\Games\Steam.exe"), now).prompt
    assert first is not None
    assert first.return_hwnd == 10
    assert (
        policy.observe(_observation(3, 20, r"C:\Games\Steam.exe"), now).prompt is None
    )

    result = policy.decide(first.id, PolicyDecision.CONTINUE)
    assert result is not None
    assert result.activate_hwnd == 20
    assert policy.observe(_observation(4, 10, r"C:\Work\Word.exe"), now).prompt is None
    second = policy.observe(_observation(5, 20, r"C:\Games\Steam.exe"), now).prompt
    assert second is not None
    assert second.id != first.id


def test_return_targets_last_allowed_window_and_stale_decisions_are_ignored() -> None:
    schedule = _schedule()
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(
        FocusConfiguration((schedule,), (_allowed(r"C:\Work\Word.exe"),))
    )
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    policy.observe(_observation(1, 10, r"C:\Work\Word.exe"), now)
    prompt = policy.observe(_observation(2, 20, r"C:\Games\Steam.exe"), now).prompt
    assert prompt is not None
    assert policy.decide("stale-id", PolicyDecision.RETURN) is None
    result = policy.decide(prompt.id, PolicyDecision.RETURN)
    assert result is not None
    assert result.activate_hwnd == 10


def test_system_own_and_unresolved_windows_never_prompt() -> None:
    schedule = _schedule()
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(FocusConfiguration((schedule,), ()))
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)

    assert (
        policy.observe(_observation(1, 10, r"C:\Windows\explorer.exe"), now).prompt
        is None
    )
    assert (
        policy.observe(
            _observation(2, 11, r"C:\Lock-In\lock-in.exe", pid=999), now
        ).prompt
        is None
    )
    unresolved = ForegroundObservation(
        sequence=3,
        observed_at="2026-09-14T13:03:00+00:00",
        monotonic_ms=300,
        hwnd=12,
        pid=None,
        application_name=None,
        executable_path=None,
        status=ResolutionStatus.PROCESS_ACCESS_DENIED,
    )
    assert policy.observe(unresolved, now).prompt is None


def test_outside_schedule_never_prompts_and_target_change_replaces_stale_prompt() -> (
    None
):
    schedule = _schedule()
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(FocusConfiguration((schedule,), ()))

    outside = policy.observe(
        _observation(1, 10, r"C:\Games\Steam.exe"),
        datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    )
    assert outside.prompt is None

    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    first = policy.observe(_observation(2, 20, r"C:\Games\Steam.exe"), now)
    replacement = policy.observe(_observation(3, 30, r"C:\Video\Player.exe"), now)
    assert first.prompt is not None
    assert replacement.dismiss_prompt
    assert replacement.prompt is not None
    assert replacement.prompt.target_hwnd == 30


def test_recent_applications_are_deduplicated_and_bounded() -> None:
    policy = ApplicationFocusPolicy(own_pid=999, recent_limit=2)
    now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    policy.observe(_observation(1, 1, r"C:\Apps\One.exe"), now)
    policy.observe(_observation(2, 2, r"C:\Apps\Two.exe"), now)
    policy.observe(_observation(3, 3, r"c:\apps\ONE.EXE"), now)

    recent = policy.recent_applications
    assert len(recent) == 2
    assert recent[0].display_name == "ONE.EXE".removesuffix(".exe")
    assert recent[1].display_name == "Two"
