from __future__ import annotations

import logging
from concurrent.futures import Future
from dataclasses import replace
from datetime import UTC, datetime, time

from lock_in.app.focus_service import FocusApplicationService
from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
    AppSettings,
    AttentionDecision,
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
)


def _completed(value):
    future = Future()
    future.set_result(value)
    return future


class FakeHistory:
    def __init__(self) -> None:
        self.sessions = []
        self.events = []

    def save_session(self, session):
        self.sessions.append(session)
        return _completed(session)

    def save_event(self, event):
        self.events.append(event)
        return _completed(event)


class FakeUi:
    def __init__(self) -> None:
        self.prompts = []
        self.dismissals = 0
        self.recent = ()
        self.captured = []

    def show_attention_prompt(self, prompt) -> None:
        self.prompts.append(prompt)

    def dismiss_attention_prompt(self) -> None:
        self.dismissals += 1

    def update_recent_applications(self, applications) -> None:
        self.recent = applications

    def application_captured(self, application) -> None:
        self.captured.append(application)


class FakeActivator:
    def __init__(self) -> None:
        self.targets = []

    def activate(self, hwnd) -> bool:
        self.targets.append(hwnd)
        return True


def _observation(sequence: int, hwnd: int, path: str) -> ForegroundObservation:
    return ForegroundObservation(
        sequence=sequence,
        observed_at=f"2026-09-14T13:0{sequence}:00+00:00",
        monotonic_ms=sequence,
        hwnd=hwnd,
        pid=sequence + 100,
        application_name=path.rsplit("\\", 1)[-1],
        executable_path=path,
        status=ResolutionStatus.IDENTIFIED,
    )


def _observation_at(
    sequence: int, hwnd: int, path: str, monotonic_ms: int
) -> ForegroundObservation:
    original = _observation(sequence, hwnd, path)
    return ForegroundObservation(
        sequence=original.sequence,
        observed_at=original.observed_at,
        monotonic_ms=monotonic_ms,
        hwnd=original.hwnd,
        pid=original.pid,
        application_name=original.application_name,
        executable_path=original.executable_path,
        status=original.status,
    )


def test_focus_service_records_prompt_and_decision_without_blocking_ui() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    allowed = ApplicationAllowlistEntry(
        schedule_id=schedule.id,
        identity=ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Word",
            executable_path=r"C:\Work\Word.exe",
        ),
    )
    history = FakeHistory()
    ui = FakeUi()
    activator = FakeActivator()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        history,
        ui,
        activator,
        logging.getLogger("test.focus.service"),
        clock=lambda: now,
    )
    service.update_focus_configuration(FocusConfiguration((schedule,), (allowed,)))

    service.observe_foreground(_observation(1, 10, r"C:\Work\Word.exe"))
    service.observe_foreground(_observation(2, 20, r"C:\Games\Steam.exe"))

    assert len(history.sessions) == 1
    assert len(ui.prompts) == 1
    assert history.events[0].decision is AttentionDecision.PROMPT_SHOWN
    prompt = ui.prompts[0]

    service.decide_prompt(prompt.id, PolicyDecision.CONTINUE)

    assert activator.targets == [20]
    assert history.events[-1].decision is AttentionDecision.CONTINUE
    assert history.events[-1].focus_session_id == history.sessions[0].id
    service.stop(1)
    assert history.sessions[-1].ended_at == now


def test_prompt_is_dismissed_after_target_activation() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    order = []

    class OrderedUi(FakeUi):
        def dismiss_attention_prompt(self) -> None:
            order.append("dismiss")
            super().dismiss_attention_prompt()

    class OrderedActivator(FakeActivator):
        def activate(self, hwnd) -> bool:
            order.append(("activate", hwnd))
            return super().activate(hwnd)

    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        FakeHistory(),
        OrderedUi(),
        OrderedActivator(),
        logging.getLogger("test.focus.activation-order"),
        clock=lambda: now,
    )
    allowed_window = ApplicationAllowlistEntry(
        identity=ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Word",
            executable_path=r"C:\Work\Word.exe",
        )
    )
    service.update_focus_configuration(
        FocusConfiguration((schedule,), (allowed_window,))
    )
    service.observe_foreground(_observation(1, 10, r"C:\Work\Word.exe"))
    service.observe_foreground(_observation(2, 20, r"C:\Games\Steam.exe"))

    prompt = service._policy.active_prompt  # noqa: SLF001
    assert prompt is not None
    service.decide_prompt(prompt.id, PolicyDecision.RETURN)

    assert order == [("activate", 10), "dismiss"]


def test_deleting_active_schedule_closes_session_without_dangling_reference() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    history = FakeHistory()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        history,
        FakeUi(),
        FakeActivator(),
        logging.getLogger("test.focus.deleted-schedule"),
        clock=lambda: now,
    )
    service.update_focus_configuration(FocusConfiguration((schedule,), ()))
    service.observe_foreground(_observation(1, 10, r"C:\Work\Word.exe"))

    service.update_focus_configuration(FocusConfiguration())

    assert history.sessions[-1].schedule_id is None
    assert history.sessions[-1].ended_at == now


def test_duplicate_foreground_event_does_not_end_active_session() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    history = FakeHistory()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        history,
        FakeUi(),
        FakeActivator(),
        logging.getLogger("test.focus.duplicate"),
        clock=lambda: now,
    )
    service.update_focus_configuration(FocusConfiguration((schedule,), ()))
    observation = _observation(1, 10, r"C:\Work\Word.exe")

    service.observe_foreground(observation)
    service.observe_foreground(observation)

    assert len(history.sessions) == 1
    assert history.sessions[0].ended_at is None


def test_capture_selects_next_external_application_without_prompting() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    history = FakeHistory()
    ui = FakeUi()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        history,
        ui,
        FakeActivator(),
        logging.getLogger("test.focus.capture"),
        clock=lambda: now,
    )
    service.update_focus_configuration(FocusConfiguration((schedule,), ()))

    service.set_application_capture(True)
    service.observe_foreground(_observation(1, 10, r"C:\Tools\Editor.exe"))

    assert [item.executable_path for item in ui.captured] == [r"C:\Tools\Editor.exe"]
    assert ui.prompts == []
    assert history.events == []

    service.observe_foreground(_observation(2, 20, r"C:\Games\Steam.exe"))

    assert len(ui.prompts) == 1
    assert history.events[0].decision is AttentionDecision.PROMPT_SHOWN


def test_follow_up_counts_foreground_time_and_repeats_only_after_continue() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    history = FakeHistory()
    ui = FakeUi()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        history,
        ui,
        FakeActivator(),
        logging.getLogger("test.focus.follow-up"),
        clock=lambda: now,
    )
    service.update_focus_configuration(
        FocusConfiguration((schedule,), (), AppSettings(follow_up_seconds=30))
    )
    target = _observation(1, 20, r"C:\Games\Steam.exe")
    service.observe_foreground(target)
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    service.observe_foreground(target)

    service.tick(now, target.monotonic_ms + 30_000)
    service.tick(now, target.monotonic_ms + 31_000)

    assert len(ui.prompts) == 2
    follow_up = ui.prompts[-1]
    assert follow_up.foreground_seconds == 30
    assert history.events[-1].foreground_seconds == 30

    service.decide_prompt(follow_up.id, PolicyDecision.CONTINUE)
    service.observe_foreground(target)
    service.tick(now, target.monotonic_ms + 61_000)

    assert len(ui.prompts) == 3


def test_context_change_invalidates_pending_follow_up() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    allowed = ApplicationAllowlistEntry(
        schedule_id=schedule.id,
        identity=ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Word",
            executable_path=r"C:\Work\Word.exe",
        ),
    )
    ui = FakeUi()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        FakeHistory(),
        ui,
        FakeActivator(),
        logging.getLogger("test.focus.stale-follow-up"),
        clock=lambda: now,
    )
    service.update_focus_configuration(
        FocusConfiguration((schedule,), (allowed,), AppSettings(follow_up_seconds=30))
    )
    target = _observation(1, 20, r"C:\Games\Steam.exe")
    service.observe_foreground(target)
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    service.observe_foreground(target)
    service.observe_foreground(_observation(2, 10, r"C:\Work\Word.exe"))

    service.tick(now, target.monotonic_ms + 60_000)

    assert len(ui.prompts) == 1


def test_lock_invalidates_timing_and_restart_has_no_elapsed_recovery() -> None:
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        id="schedule-1",
        name="Focus",
        start_time=time(13, 0),
        end_time=time(13, 40),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )
    configuration = FocusConfiguration(
        (schedule,), (), AppSettings(follow_up_seconds=30)
    )
    ui = FakeUi()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        FakeHistory(),
        ui,
        FakeActivator(),
        logging.getLogger("test.focus.lock"),
        clock=lambda: now,
    )
    service.update_focus_configuration(configuration)
    target = _observation(1, 20, r"C:\Games\Steam.exe")
    service.observe_foreground(target)
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    service.observe_foreground(target)
    service.system_availability_changed(False, target.monotonic_ms + 10_000)
    service.system_availability_changed(True, target.monotonic_ms + 500_000)
    service.tick(now, target.monotonic_ms + 900_000)
    service.observe_foreground(
        _observation_at(
            2,
            target.hwnd or 20,
            target.executable_path or r"C:\Games\Steam.exe",
            target.monotonic_ms + 900_001,
        )
    )
    service.tick(now, target.monotonic_ms + 920_001)

    restarted_ui = FakeUi()
    restarted = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        FakeHistory(),
        restarted_ui,
        FakeActivator(),
        logging.getLogger("test.focus.restart"),
        clock=lambda: now,
    )
    restarted.update_focus_configuration(configuration)
    restarted.tick(now, target.monotonic_ms + 1_000_000)

    assert len(ui.prompts) == 2
    assert ui.prompts[-1].foreground_seconds == 30
    assert restarted_ui.prompts == []


def _review_regression_service():
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)
    schedule = Schedule(
        "Work",
        time(13),
        time(14),
        "UTC",
        (Recurrence(RecurrenceKind.WEEKLY, weekday=0),),
    )
    config = FocusConfiguration((schedule,), settings=AppSettings(follow_up_seconds=30))
    history, ui = FakeHistory(), FakeUi()
    service = FocusApplicationService(
        ApplicationFocusPolicy(own_pid=999),
        history,
        ui,
        FakeActivator(),
        logging.getLogger("regression.focus"),
        clock=lambda: now,
    )
    service.update_focus_configuration(config)
    return service, ui, history, config, now


def test_own_window_pauses_timing_and_configuration_reload_keeps_progress():
    service, ui, _, config, now = _review_regression_service()
    target = _observation_at(1, 20, r"C:\Games\Steam.exe", 0)
    service.observe_foreground(target)
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    service.observe_foreground(target)
    service.observe_foreground(replace(target, hwnd=999, pid=999, monotonic_ms=10000))
    service.tick(now, 100000)
    assert len(ui.prompts) == 1
    service.update_focus_configuration(config)
    service.observe_foreground(replace(target, monotonic_ms=100001))
    service.tick(now, 120001)
    assert len(ui.prompts) == 2
    assert ui.prompts[-1].foreground_seconds == 30


def test_configuration_allowlisting_current_target_dismisses_pending_prompt():
    service, ui, _, config, _ = _review_regression_service()
    target = _observation_at(1, 20, r"C:\Games\Steam.exe", 0)
    service.observe_foreground(target)
    count = ui.dismissals
    entry = ApplicationAllowlistEntry(
        ApplicationIdentity(
            ApplicationKind.WIN32, "Steam", executable_path=target.executable_path
        )
    )
    service.update_focus_configuration(replace(config, applications=(entry,)))
    assert ui.dismissals == count + 1
    assert service._policy.active_prompt is None


def test_activation_exception_cannot_leave_decision_dialog_pending():
    service, ui, history, _, _ = _review_regression_service()

    class BrokenActivator:
        def activate(self, _hwnd):
            raise OSError("window closed")

    service._activator = BrokenActivator()
    service.observe_foreground(_observation_at(1, 20, r"C:\Game.exe", 0))
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    assert ui.dismissals == 1
    assert history.events[-1].decision is AttentionDecision.CONTINUE


def test_browser_prompt_own_focus_continue_and_followup_end_to_end():
    from lock_in.context.application_service import BrowserContextApplicationService

    service, ui, _, _, now = _review_regression_service()
    sent = []
    browser = BrowserContextApplicationService(
        service, lambda _id, message: sent.append(message) or True, own_pid=999
    )
    browser.browser_event(
        {
            "event": "connected",
            "connectionId": "a",
            "clientInstanceId": "profile",
            "browser": "chrome",
        },
        0,
    )
    chrome = _observation_at(1, 20, r"C:\Chrome\chrome.exe", 0)

    def resolve(at, seq):
        correlation = sent[-1]["payload"]
        browser.browser_event(
            {
                "event": "browser_context_snapshot",
                "connectionId": "a",
                "clientInstanceId": "profile",
                "browser": "chrome",
                "sequence": seq,
                "payload": {
                    "windowId": 1,
                    "tabId": 2,
                    "domain": "youtube.com",
                    "windowFocused": True,
                    **correlation,
                },
            },
            at,
        )

    browser.foreground_observed(chrome, 0)
    resolve(10, 1)
    browser.foreground_observed(replace(chrome, hwnd=999, pid=999, monotonic_ms=20), 20)
    assert service._policy.active_prompt is not None
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    browser.foreground_observed(replace(chrome, monotonic_ms=30), 30)
    resolve(40, 2)
    assert len(ui.prompts) == 1
    service.tick(now, 30040)
    assert len(ui.prompts) == 2
    assert ui.prompts[-1].target_key == "youtube.com"
    assert ui.prompts[-1].foreground_seconds == 30


def test_clock_rollback_can_close_sessions():
    service, _, history, _, now = _review_regression_service()
    service._clock = lambda: now.replace(hour=12)
    service.stop(1)
    assert history.sessions[-1].ended_at == history.sessions[-1].started_at


def test_renamed_schedule_updates_prompt_without_recording_another_entry():
    service, ui, history, config, _ = _review_regression_service()
    service.observe_foreground(_observation_at(1, 20, r"C:\Game.exe", 0))
    prompt_id = ui.prompts[-1].id
    original_count = len(history.events)
    renamed = replace(config.schedules[0], name="Renamed work")
    service.update_focus_configuration(replace(config, schedules=(renamed,)))
    assert ui.prompts[-1].id == prompt_id
    assert ui.prompts[-1].schedule_names == ("Renamed work",)
    assert len(history.events) == original_count


def test_new_allowlist_clears_continued_target_and_prevents_followup():
    service, ui, _, config, now = _review_regression_service()
    target = _observation_at(1, 20, r"C:\Games\Steam.exe", 0)
    service.observe_foreground(target)
    service.decide_prompt(ui.prompts[-1].id, PolicyDecision.CONTINUE)
    service.observe_foreground(target)
    entry = ApplicationAllowlistEntry(
        ApplicationIdentity(
            ApplicationKind.WIN32, "Steam", executable_path=target.executable_path
        )
    )
    service.update_focus_configuration(replace(config, applications=(entry,)))
    service.tick(now, 60000)
    assert len(ui.prompts) == 1
    assert service._timer.target_key is None
