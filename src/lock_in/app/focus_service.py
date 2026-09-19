"""Application-only focus loop orchestration."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime
from typing import Protocol

from lock_in.app.logging_setup import safe_log
from lock_in.domain.models import (
    AttentionDecision,
    AttentionEvent,
    FocusSession,
    TargetType,
)
from lock_in.platform.windows.foreground_monitor import ForegroundObservation
from lock_in.rules.application_policy import (
    ApplicationFocusPolicy,
    AttentionPrompt,
    FocusConfiguration,
    PolicyDecision,
    RecentApplication,
    normalize_windows_path,
)
from lock_in.storage.repositories import HistoryRepository


class FocusUiPort(Protocol):
    def show_attention_prompt(self, prompt: AttentionPrompt) -> None: ...

    def dismiss_attention_prompt(self) -> None: ...

    def update_recent_applications(
        self, applications: tuple[RecentApplication, ...]
    ) -> None: ...

    def application_captured(self, application: RecentApplication) -> None: ...


class WindowActivationPort(Protocol):
    def activate(self, hwnd: int | None) -> bool: ...


class FocusApplicationService:
    name = "focus_service"

    def __init__(
        self,
        policy: ApplicationFocusPolicy,
        history: HistoryRepository,
        ui: FocusUiPort,
        activator: WindowActivationPort,
        logger: logging.Logger,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy
        self._history = history
        self._ui = ui
        self._activator = activator
        self._logger = logger
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._sessions: dict[str, FocusSession] = {}
        self._pending_writes: set[Future[object]] = set()
        self._writes_lock = threading.Lock()
        self._capture_next_application = False

    def start(self) -> None:
        return

    def stop(self, timeout: float) -> None:
        now = self._clock()
        for session in tuple(self._sessions.values()):
            self._queue_write(
                self._history.save_session(
                    FocusSession(
                        id=session.id,
                        schedule_id=session.schedule_id,
                        started_at=session.started_at,
                        ended_at=now,
                    )
                ),
                "close_focus_session",
            )
        self._sessions.clear()
        deadline = time.monotonic() + timeout
        with self._writes_lock:
            pending = tuple(self._pending_writes)
        for future in pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                future.result(timeout=remaining)
            except BaseException:
                continue

    def update_focus_configuration(self, configuration: FocusConfiguration) -> None:
        configured_ids = {schedule.id for schedule in configuration.schedules}
        now = self._clock()
        for schedule_id, session in tuple(self._sessions.items()):
            if schedule_id in configured_ids:
                continue
            self._queue_write(
                self._history.save_session(
                    FocusSession(
                        id=session.id,
                        schedule_id=None,
                        started_at=session.started_at,
                        ended_at=now,
                    )
                ),
                "close_deleted_schedule_session",
            )
            del self._sessions[schedule_id]
        self._policy.update_configuration(configuration)

    def observe_foreground(self, observation: ForegroundObservation) -> None:
        now = self._clock()
        update = self._policy.observe(observation, now)
        if update.active_schedules is not None:
            self._sync_sessions(update.active_schedules, now)
        if update.recent_applications is not None:
            self._ui.update_recent_applications(update.recent_applications)
            if self._capture_next_application:
                self._capture_next_application = False
                self._policy.cancel_prompt()
                self._ui.dismiss_attention_prompt()
                self._ui.application_captured(update.recent_applications[0])
                return
        if update.dismiss_prompt:
            self._ui.dismiss_attention_prompt()
        if update.prompt is not None:
            self._record_attention(
                update.prompt,
                AttentionDecision.PROMPT_SHOWN,
                now,
            )
            self._ui.show_attention_prompt(update.prompt)

    def set_application_capture(self, enabled: bool) -> None:
        self._capture_next_application = enabled

    def decide_prompt(self, prompt_id: str, decision: PolicyDecision) -> None:
        result = self._policy.decide(prompt_id, decision)
        if result is None:
            return
        self._ui.dismiss_attention_prompt()
        self._activator.activate(result.activate_hwnd)
        recorded = (
            AttentionDecision.RETURN
            if decision is PolicyDecision.RETURN
            else AttentionDecision.CONTINUE
        )
        self._record_attention(result.prompt, recorded, self._clock())

    def _sync_sessions(self, active_schedules, now: datetime) -> None:
        active_ids = {schedule.id for schedule in active_schedules}
        for schedule_id, session in tuple(self._sessions.items()):
            if schedule_id in active_ids:
                continue
            self._queue_write(
                self._history.save_session(
                    FocusSession(
                        id=session.id,
                        schedule_id=session.schedule_id,
                        started_at=session.started_at,
                        ended_at=now,
                    )
                ),
                "close_focus_session",
            )
            del self._sessions[schedule_id]
        for schedule in active_schedules:
            if schedule.id in self._sessions:
                continue
            session = FocusSession(schedule_id=schedule.id, started_at=now)
            self._sessions[schedule.id] = session
            self._queue_write(
                self._history.save_session(session), "start_focus_session"
            )

    def _record_attention(
        self,
        prompt: AttentionPrompt,
        decision: AttentionDecision,
        occurred_at: datetime,
    ) -> None:
        session = next(
            (
                self._sessions[schedule_id]
                for schedule_id in prompt.schedule_ids
                if schedule_id in self._sessions
            ),
            None,
        )
        if session is None:
            return
        self._queue_write(
            self._history.save_event(
                AttentionEvent(
                    focus_session_id=session.id,
                    occurred_at=occurred_at,
                    target_type=TargetType.APPLICATION,
                    target_key=normalize_windows_path(prompt.executable_path),
                    decision=decision,
                )
            ),
            "save_attention_event",
        )

    def _queue_write(self, future: Future[object], operation: str) -> None:
        with self._writes_lock:
            self._pending_writes.add(future)

        def complete(completed: Future[object]) -> None:
            with self._writes_lock:
                self._pending_writes.discard(completed)
            try:
                completed.result()
            except BaseException as error:
                safe_log(
                    self._logger,
                    logging.ERROR,
                    "history_write_failed",
                    component="focus_service",
                    operation=operation,
                    exception_type=type(error).__name__,
                )

        future.add_done_callback(complete)
