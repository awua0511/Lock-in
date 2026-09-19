"""Pure application-only schedule and entry-prompt policy."""

from __future__ import annotations

import ntpath
import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lock_in.domain.models import ApplicationAllowlistEntry, Recurrence, Schedule
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)

SYSTEM_EXECUTABLES = frozenset(
    {
        "applicationframehost.exe",
        "dwm.exe",
        "explorer.exe",
        "lockapp.exe",
        "searchhost.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "taskhostw.exe",
    }
)


def normalize_windows_path(path: str) -> str:
    """Normalize an absolute Windows path for case-insensitive identity matching."""

    value = path.strip().strip('"')
    if not value:
        raise ValueError("executable path must not be empty")
    return ntpath.normcase(ntpath.normpath(value))


def executable_name(path: str) -> str:
    return ntpath.basename(normalize_windows_path(path)).lower()


@dataclass(frozen=True, slots=True)
class FocusConfiguration:
    schedules: tuple[Schedule, ...] = ()
    applications: tuple[ApplicationAllowlistEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class RecentApplication:
    display_name: str
    executable_path: str
    last_observed_at: str


@dataclass(frozen=True, slots=True)
class AttentionPrompt:
    id: str
    target_hwnd: int
    target_pid: int
    application_name: str
    executable_path: str
    return_hwnd: int | None
    schedule_ids: tuple[str, ...]
    schedule_names: tuple[str, ...]


class PolicyDecision(StrEnum):
    RETURN = "return"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class DecisionResult:
    prompt: AttentionPrompt
    decision: PolicyDecision
    activate_hwnd: int | None


@dataclass(frozen=True, slots=True)
class PolicyUpdate:
    prompt: AttentionPrompt | None = None
    dismiss_prompt: bool = False
    recent_applications: tuple[RecentApplication, ...] | None = None
    active_schedules: tuple[Schedule, ...] | None = None


def active_schedules_at(
    schedules: tuple[Schedule, ...], now: datetime
) -> tuple[Schedule, ...]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("schedule evaluation requires an aware datetime")
    active = [schedule for schedule in schedules if _schedule_is_active(schedule, now)]
    return tuple(sorted(active, key=lambda item: item.id))


def _schedule_is_active(schedule: Schedule, now: datetime) -> bool:
    if not schedule.enabled:
        return False
    try:
        if schedule.timezone == "local":
            local = now.astimezone()
        elif schedule.timezone == "UTC":
            local = now.astimezone(UTC)
        else:
            local = now.astimezone(ZoneInfo(schedule.timezone))
    except ZoneInfoNotFoundError:
        return False

    local_time = local.timetz().replace(tzinfo=None)
    if schedule.start_time < schedule.end_time:
        return (
            schedule.start_time <= local_time < schedule.end_time
            and _matches_recurrence(schedule.recurrences, local.date())
        )

    if local_time >= schedule.start_time:
        occurrence_date = local.date()
    elif local_time < schedule.end_time:
        occurrence_date = local.date() - timedelta(days=1)
    else:
        return False
    return _matches_recurrence(schedule.recurrences, occurrence_date)


def _matches_recurrence(
    recurrences: tuple[Recurrence, ...], occurrence_date: date
) -> bool:
    return any(
        recurrence.occurrence_date == occurrence_date
        if recurrence.occurrence_date is not None
        else recurrence.weekday == occurrence_date.weekday()
        for recurrence in recurrences
    )


class ApplicationFocusPolicy:
    """Track entries and request at most one prompt per disallowed entry."""

    def __init__(self, *, own_pid: int | None = None, recent_limit: int = 20) -> None:
        if recent_limit < 1:
            raise ValueError("recent_limit must be positive")
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._recent_limit = recent_limit
        self._configuration = FocusConfiguration()
        self._recent: OrderedDict[str, RecentApplication] = OrderedDict()
        self._current_key: tuple[int, str] | None = None
        self._continued_key: tuple[int, str] | None = None
        self._last_allowed_hwnd: int | None = None
        self._prompt: AttentionPrompt | None = None

    @property
    def active_prompt(self) -> AttentionPrompt | None:
        return self._prompt

    @property
    def recent_applications(self) -> tuple[RecentApplication, ...]:
        return tuple(reversed(self._recent.values()))

    def update_configuration(self, configuration: FocusConfiguration) -> None:
        self._configuration = configuration

    def observe(
        self, observation: ForegroundObservation, now: datetime
    ) -> PolicyUpdate:
        if observation.pid == self._own_pid:
            return PolicyUpdate()

        if (
            observation.status is not ResolutionStatus.IDENTIFIED
            or observation.hwnd is None
            or observation.pid is None
            or not observation.executable_path
        ):
            dismiss = self._cancel_if_target_changed(observation.hwnd)
            return PolicyUpdate(dismiss_prompt=dismiss)

        path = normalize_windows_path(observation.executable_path)
        key = (observation.hwnd, path)
        if key == self._current_key:
            return PolicyUpdate()
        self._current_key = key

        if self._continued_key is not None and key != self._continued_key:
            self._continued_key = None

        recent = self._observe_recent(observation, path)
        active = active_schedules_at(self._configuration.schedules, now)
        allowed = (
            not active or self._is_system_path(path) or self._is_allowed(path, active)
        )
        if allowed:
            self._last_allowed_hwnd = observation.hwnd
            dismiss = self._prompt is not None
            self._prompt = None
            return PolicyUpdate(
                dismiss_prompt=dismiss,
                recent_applications=recent,
                active_schedules=active,
            )

        if key == self._continued_key:
            return PolicyUpdate(recent_applications=recent, active_schedules=active)

        prompt = AttentionPrompt(
            id=str(uuid.uuid4()),
            target_hwnd=observation.hwnd,
            target_pid=observation.pid,
            application_name=observation.application_name or "Unknown application",
            executable_path=observation.executable_path,
            return_hwnd=self._last_allowed_hwnd,
            schedule_ids=tuple(schedule.id for schedule in active),
            schedule_names=tuple(schedule.name for schedule in active),
        )
        dismiss = self._prompt is not None
        self._prompt = prompt
        return PolicyUpdate(
            prompt=prompt,
            dismiss_prompt=dismiss,
            recent_applications=recent,
            active_schedules=active,
        )

    def decide(self, prompt_id: str, decision: PolicyDecision) -> DecisionResult | None:
        prompt = self._prompt
        if prompt is None or prompt.id != prompt_id:
            return None
        self._prompt = None
        key = (prompt.target_hwnd, normalize_windows_path(prompt.executable_path))
        if decision is PolicyDecision.CONTINUE:
            self._continued_key = key
            activate_hwnd = prompt.target_hwnd
        else:
            self._continued_key = None
            activate_hwnd = prompt.return_hwnd
        return DecisionResult(prompt, decision, activate_hwnd)

    def cancel_prompt(self) -> None:
        """Discard a prompt created while selecting an application."""
        self._prompt = None

    def _is_allowed(self, path: str, schedules: tuple[Schedule, ...]) -> bool:
        active_ids = {schedule.id for schedule in schedules}
        return any(
            entry.enabled
            and entry.identity.executable_path is not None
            and normalize_windows_path(entry.identity.executable_path) == path
            and (entry.schedule_id is None or entry.schedule_id in active_ids)
            for entry in self._configuration.applications
        )

    def _observe_recent(
        self, observation: ForegroundObservation, normalized_path: str
    ) -> tuple[RecentApplication, ...] | None:
        if self._is_system_path(normalized_path):
            return None
        application = RecentApplication(
            display_name=observation.application_name
            or executable_name(normalized_path),
            executable_path=observation.executable_path or normalized_path,
            last_observed_at=observation.observed_at,
        )
        self._recent.pop(normalized_path, None)
        self._recent[normalized_path] = application
        while len(self._recent) > self._recent_limit:
            self._recent.popitem(last=False)
        return self.recent_applications

    def _is_system_path(self, path: str) -> bool:
        return executable_name(path) in SYSTEM_EXECUTABLES

    def _cancel_if_target_changed(self, hwnd: int | None) -> bool:
        if self._prompt is None or hwnd in {None, self._prompt.target_hwnd}:
            return False
        self._prompt = None
        self._current_key = None
        return True
