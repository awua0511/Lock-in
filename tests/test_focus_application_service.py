from __future__ import annotations

import logging
from concurrent.futures import Future
from datetime import UTC, datetime, time

from lock_in.app.focus_service import FocusApplicationService
from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
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
