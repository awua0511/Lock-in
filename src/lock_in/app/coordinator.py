"""Framework-independent application event coordinator."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from lock_in.app.configuration_service import ConfigurationService
from lock_in.app.events import (
    ApplicationEvent,
    ApplicationEventKind,
    BrowserIpcEvent,
    PromptDecisionEvent,
    SystemAvailabilityEvent,
    TimingTickEvent,
)
from lock_in.app.focus_service import FocusApplicationService
from lock_in.app.logging_setup import safe_log
from lock_in.context.application_service import BrowserContextApplicationService
from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    AppSettings,
    Schedule,
    WebsiteAllowlistEntry,
)
from lock_in.platform.windows.foreground_monitor import ForegroundObservation
from lock_in.rules.application_policy import FocusConfiguration, PolicyDecision


class UiPort(Protocol):
    """Thread-safe commands implemented by a UI signal bridge."""

    def show_main_window(self) -> None: ...

    def request_quit(self) -> None: ...

    def report_component_failure(self, component: str) -> None: ...

    def update_focus_configuration(self, configuration: FocusConfiguration) -> None: ...


class ApplicationCoordinator:
    def __init__(
        self,
        ui: UiPort,
        logger: logging.Logger,
        *,
        configuration: ConfigurationService | None = None,
        focus: FocusApplicationService | None = None,
        browser_context: BrowserContextApplicationService | None = None,
        on_explicit_exit: Callable[[], None] | None = None,
    ) -> None:
        self._ui = ui
        self._logger = logger
        self._configuration = configuration
        self._focus = focus
        self._browser_context = browser_context
        self._on_explicit_exit = on_explicit_exit or (lambda: None)

    def handle(self, event: ApplicationEvent) -> None:
        safe_log(
            self._logger,
            logging.INFO,
            "application_event",
            event_kind=event.kind.value,
        )
        if event.kind is ApplicationEventKind.SHOW_MAIN_WINDOW:
            self._ui.show_main_window()
        elif event.kind is ApplicationEventKind.SHUTDOWN_REQUESTED:
            try:
                self._on_explicit_exit()
            except OSError:
                safe_log(self._logger, logging.WARNING, "exit_marker_write_failed")
            self._ui.request_quit()
        elif event.kind is ApplicationEventKind.COMPONENT_FAILED:
            component = event.field("component") or "unknown"
            self._ui.report_component_failure(component)
        elif (
            event.kind is ApplicationEventKind.FOREGROUND_OBSERVED
            and (self._browser_context is not None or self._focus is not None)
            and isinstance(event.payload, ForegroundObservation)
        ):
            if self._browser_context is not None:
                self._browser_context.foreground_observed(
                    event.payload, event.payload.monotonic_ms
                )
            elif self._focus is not None:
                self._focus.observe_foreground(event.payload)
        elif (
            event.kind is ApplicationEventKind.BROWSER_IPC_EVENT
            and self._browser_context is not None
            and isinstance(event.payload, BrowserIpcEvent)
        ):
            self._browser_context.browser_event(
                event.payload.event, event.payload.monotonic_ms
            )
        elif (
            event.kind is ApplicationEventKind.PROMPT_DECIDED
            and self._focus is not None
            and isinstance(event.payload, PromptDecisionEvent)
        ):
            self._focus.decide_prompt(
                event.payload.prompt_id,
                PolicyDecision(event.payload.decision),
            )
        elif (
            event.kind is ApplicationEventKind.CONFIGURATION_LOADED
            and self._focus is not None
            and isinstance(event.payload, FocusConfiguration)
        ):
            self._focus.update_focus_configuration(event.payload)
            self._ui.update_focus_configuration(event.payload)
        elif (
            event.kind is ApplicationEventKind.SET_APPLICATION_CAPTURE
            and self._focus is not None
            and isinstance(event.payload, bool)
        ):
            self._focus.set_application_capture(event.payload)
        elif (
            event.kind is ApplicationEventKind.TIMING_TICK
            and self._focus is not None
            and isinstance(event.payload, TimingTickEvent)
            and isinstance(event.payload.wall_time, datetime)
        ):
            if self._browser_context is not None:
                self._browser_context.tick(event.payload.monotonic_ms)
            self._focus.tick(event.payload.wall_time, event.payload.monotonic_ms)
        elif (
            event.kind is ApplicationEventKind.SYSTEM_AVAILABILITY_CHANGED
            and self._focus is not None
            and isinstance(event.payload, SystemAvailabilityEvent)
        ):
            self._focus.system_availability_changed(
                event.payload.available, event.payload.monotonic_ms
            )
        elif self._configuration is not None:
            self._handle_configuration(event)

    def _handle_configuration(self, event: ApplicationEvent) -> None:
        if event.kind is ApplicationEventKind.SAVE_SCHEDULE and isinstance(
            event.payload, Schedule
        ):
            self._configuration.save_schedule(event.payload)
        elif event.kind is ApplicationEventKind.DELETE_SCHEDULE and isinstance(
            event.payload, str
        ):
            self._configuration.delete_schedule(event.payload)
        elif (
            event.kind is ApplicationEventKind.SAVE_APPLICATION_ALLOWLIST
            and isinstance(event.payload, ApplicationAllowlistEntry)
        ):
            self._configuration.save_application(event.payload)
        elif (
            event.kind is ApplicationEventKind.DELETE_APPLICATION_ALLOWLIST
            and isinstance(event.payload, str)
        ):
            self._configuration.delete_application(event.payload)
        elif event.kind is ApplicationEventKind.SAVE_SETTINGS and isinstance(
            event.payload, AppSettings
        ):
            self._configuration.save_settings(event.payload)
        elif event.kind is ApplicationEventKind.SAVE_WEBSITE_ALLOWLIST and isinstance(
            event.payload, WebsiteAllowlistEntry
        ):
            self._configuration.save_website(event.payload)
        elif event.kind is ApplicationEventKind.DELETE_WEBSITE_ALLOWLIST and isinstance(
            event.payload, str
        ):
            self._configuration.delete_website(event.payload)
