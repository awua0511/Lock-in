"""Typed events crossing production component boundaries."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ApplicationEventKind(StrEnum):
    STARTED = "started"
    SHOW_MAIN_WINDOW = "show_main_window"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    COMPONENT_FAILED = "component_failed"
    FOREGROUND_OBSERVED = "foreground_observed"
    PROMPT_DECIDED = "prompt_decided"
    SAVE_SCHEDULE = "save_schedule"
    DELETE_SCHEDULE = "delete_schedule"
    SAVE_APPLICATION_ALLOWLIST = "save_application_allowlist"
    DELETE_APPLICATION_ALLOWLIST = "delete_application_allowlist"
    SAVE_WEBSITE_ALLOWLIST = "save_website_allowlist"
    DELETE_WEBSITE_ALLOWLIST = "delete_website_allowlist"
    SET_APPLICATION_CAPTURE = "set_application_capture"
    SAVE_SETTINGS = "save_settings"
    TIMING_TICK = "timing_tick"
    SYSTEM_AVAILABILITY_CHANGED = "system_availability_changed"
    BROWSER_IPC_EVENT = "browser_ipc_event"
    CONFIGURATION_LOADED = "configuration_loaded"
    REQUEST_REVIEW = "request_review"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_NOTIFICATION_RESULT = "review_notification_result"


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    kind: ApplicationEventKind
    source: str
    fields: tuple[tuple[str, str], ...] = ()
    payload: object | None = None
    monotonic_ns: int = field(default_factory=time.monotonic_ns)

    @classmethod
    def component_failed(
        cls, component: str, operation: str, error: BaseException
    ) -> ApplicationEvent:
        return cls(
            kind=ApplicationEventKind.COMPONENT_FAILED,
            source="lifecycle",
            fields=(
                ("component", component),
                ("operation", operation),
                ("exception_type", type(error).__name__),
            ),
        )

    def field(self, name: str) -> str | None:
        return dict(self.fields).get(name)


@dataclass(frozen=True, slots=True)
class PromptDecisionEvent:
    prompt_id: str
    decision: str


@dataclass(frozen=True, slots=True)
class TimingTickEvent:
    wall_time: datetime
    monotonic_ms: int


@dataclass(frozen=True, slots=True)
class SystemAvailabilityEvent:
    available: bool
    monotonic_ms: int
    reason: str


@dataclass(frozen=True, slots=True)
class BrowserIpcEvent:
    event: dict[str, object]
    monotonic_ms: int
