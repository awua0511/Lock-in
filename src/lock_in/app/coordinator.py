"""Framework-independent application event coordinator."""

from __future__ import annotations

import logging
from typing import Protocol

from lock_in.app.events import ApplicationEvent, ApplicationEventKind
from lock_in.app.logging_setup import safe_log


class UiPort(Protocol):
    """Thread-safe commands implemented by a UI signal bridge."""

    def show_main_window(self) -> None: ...

    def request_quit(self) -> None: ...

    def report_component_failure(self, component: str) -> None: ...


class ApplicationCoordinator:
    def __init__(self, ui: UiPort, logger: logging.Logger) -> None:
        self._ui = ui
        self._logger = logger

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
            self._ui.request_quit()
        elif event.kind is ApplicationEventKind.COMPONENT_FAILED:
            component = event.field("component") or "unknown"
            self._ui.report_component_failure(component)
