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
from lock_in.context.aggregator import ContextResolution, ForegroundContext
from lock_in.domain.models import (
    AttentionDecision,
    AttentionEvent,
    FocusSession,
)
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)
from lock_in.rules.application_policy import (
    ApplicationFocusPolicy,
    AttentionPrompt,
    FocusConfiguration,
    PolicyDecision,
    RecentApplication,
    normalize_windows_path,
)
from lock_in.sessions.foreground_timer import ContinuedUseTimer
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
        reviews=None,
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
        self._timer = ContinuedUseTimer()
        self._reviews = reviews
        self._own_foreground = False
        self._available = True

    def start(self) -> None:
        self._history.close_interrupted_sessions().result(timeout=3)

    def stop(self, timeout: float) -> None:
        now = self._clock()
        for session in tuple(self._sessions.values()):
            self._queue_write(
                self._history.save_session(
                    FocusSession(
                        id=session.id,
                        schedule_id=session.schedule_id,
                        started_at=session.started_at,
                        ended_at=max(now, session.started_at),
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
        if self._reviews is not None:
            self._reviews.update_focus_configuration(configuration)
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
                        ended_at=max(now, session.started_at),
                    )
                ),
                "close_deleted_schedule_session",
            )
            del self._sessions[schedule_id]
        self._policy.update_configuration(configuration)
        self._timer.set_threshold(configuration.settings.follow_up_seconds)
        update = self._policy.refresh(now)
        if update.active_schedules is not None:
            self._sync_sessions(update.active_schedules, now)
        if update.dismiss_prompt:
            self._ui.dismiss_attention_prompt()
        if update.prompt is not None:
            self._ui.show_attention_prompt(update.prompt)
        if self._policy.continued_key is None:
            self._timer.cancel()

    def observe_foreground(self, observation: ForegroundObservation) -> None:
        if self._reviews is not None:
            self._reviews.observe_foreground(observation)
        if not self._available:
            return
        if self._policy.is_own_observation(observation):
            self._own_foreground = True
            self._timer.suspend(observation.monotonic_ms)
            return
        if self._own_foreground:
            self._own_foreground = False
            self._timer.resume()
        now = self._clock()
        update = self._policy.observe(observation, now)
        if not self._policy.is_own_observation(observation):
            timing_key = None
            if (
                observation.status is ResolutionStatus.IDENTIFIED
                and observation.hwnd is not None
                and observation.executable_path
            ):
                timing_key = (
                    observation.hwnd,
                    normalize_windows_path(observation.executable_path),
                )
            if observation.executable_path and observation.executable_path.replace(
                "/", "\\"
            ).rsplit("\\", 1)[-1].lower() in {"chrome.exe", "msedge.exe"}:
                self._timer.suspend(observation.monotonic_ms)
            else:
                self._timer.observe(timing_key, observation.monotonic_ms)
            if self._policy.continued_key is None:
                self._timer.cancel()
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
        # Activate while the decision dialog still owns foreground permission.
        try:
            activated = self._activator.activate(result.activate_hwnd)
        except Exception:
            activated = False
        if result.activate_hwnd is not None and not activated:
            safe_log(
                self._logger,
                logging.WARNING,
                "window_activation_failed",
                operation="activate_decision_target",
                state="foreground_request_denied",
            )
        self._ui.dismiss_attention_prompt()
        if decision is PolicyDecision.CONTINUE:
            self._timer.arm(
                (
                    result.prompt.target_hwnd,
                    result.prompt.target_key
                    or normalize_windows_path(result.prompt.executable_path),
                )
            )
        else:
            self._timer.cancel()
        recorded = (
            AttentionDecision.RETURN
            if decision is PolicyDecision.RETURN
            else AttentionDecision.CONTINUE
        )
        self._record_attention(result.prompt, recorded, self._clock())

    def observe_website_context(
        self,
        context: ForegroundContext | None,
        *,
        hwnd: int,
        pid: int,
        executable_path: str,
        browser_name: str,
        monotonic_ms: int | None = None,
    ) -> None:
        if not self._available or self._own_foreground:
            return
        monotonic_ms = (
            time.monotonic_ns() // 1_000_000 if monotonic_ms is None else monotonic_ms
        )
        if self._reviews is not None:
            self._reviews.observe_website_context(context, hwnd)
        if (
            context is None
            or context.resolution is not ContextResolution.RESOLVED
            or context.browser is None
            or not context.website_evaluation_allowed
        ):
            preserve_continued = (
                context is not None and context.application.browser_kind is not None
            )
            if self._policy.invalidate_website_context(
                preserve_continued=preserve_continued
            ):
                self._ui.dismiss_attention_prompt()
            if self._timer.target_key is not None:
                if preserve_continued:
                    self._timer.suspend(monotonic_ms)
                elif self._timer.target_key[1] != normalize_windows_path(
                    executable_path or "unknown"
                ):
                    self._timer.cancel()
            return
        update = self._policy.observe_website(
            context_id=context.context_id,
            foreground_epoch=context.foreground_epoch,
            revision=context.context_revision,
            hwnd=hwnd,
            pid=pid,
            browser_name=browser_name,
            executable_path=executable_path,
            domain=context.browser.domain,
            now=self._clock(),
        )
        now = self._clock()
        if self._policy.continued_key is None:
            self._timer.cancel()
        else:
            self._timer.resume()
            self._timer.observe((hwnd, context.browser.domain), monotonic_ms)
        if update.active_schedules is not None:
            self._sync_sessions(update.active_schedules, now)
        if update.dismiss_prompt:
            self._ui.dismiss_attention_prompt()
        if update.prompt is not None:
            self._record_attention(update.prompt, AttentionDecision.PROMPT_SHOWN, now)
            self._ui.show_attention_prompt(update.prompt)

    def tick(self, now: datetime, monotonic_ms: int) -> None:
        if not self._available:
            return
        update = self._policy.refresh(now)
        if update.active_schedules is not None:
            self._sync_sessions(update.active_schedules, now)
        if update.dismiss_prompt:
            self._ui.dismiss_attention_prompt()
        if update.prompt is not None:
            self._ui.show_attention_prompt(update.prompt)
        if self._policy.continued_key is None:
            self._timer.cancel()
            return
        due = self._timer.tick(monotonic_ms)
        if due is None:
            return
        prompt = self._policy.follow_up(due.foreground_ms // 1000, now)
        if prompt is None:
            self._timer.cancel()
            return
        self._record_attention(prompt, AttentionDecision.PROMPT_SHOWN, now)
        self._ui.show_attention_prompt(prompt)

    def system_availability_changed(self, available: bool, monotonic_ms: int) -> None:
        self._available = available
        if self._reviews is not None:
            self._reviews.availability(available, monotonic_ms)
        if available:
            self._timer.resume()
            return
        self._timer.suspend(monotonic_ms)
        if self._policy.pause_for_system_unavailability():
            self._ui.dismiss_attention_prompt()

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
                        ended_at=max(now, session.started_at),
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
                    target_type=prompt.target_type,
                    target_key=prompt.target_key
                    or normalize_windows_path(prompt.executable_path),
                    decision=decision,
                    foreground_seconds=prompt.foreground_seconds,
                    prompt_kind="follow_up" if prompt.foreground_seconds else "entry",
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
