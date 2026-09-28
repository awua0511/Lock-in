"""Pure application-only schedule and entry-prompt policy."""

from __future__ import annotations

import ntpath
import os
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    AppSettings,
    Recurrence,
    Schedule,
    TargetType,
    WebsiteAllowlistEntry,
    normalize_domain,
)
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
        "chrome.exe",
        "msedge.exe",
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
    settings: AppSettings = AppSettings()
    websites: tuple[WebsiteAllowlistEntry, ...] = ()


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
    foreground_seconds: int = 0
    target_type: TargetType = TargetType.APPLICATION
    target_key: str | None = None


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
        self._last_non_browser_window_hwnd: int | None = None
        self._prompt: AttentionPrompt | None = None
        self._continued_prompt: AttentionPrompt | None = None
        self._website_current_key: tuple[int, str] | None = None

    @property
    def active_prompt(self) -> AttentionPrompt | None:
        return self._prompt

    @property
    def recent_applications(self) -> tuple[RecentApplication, ...]:
        return tuple(reversed(self._recent.values()))

    @property
    def continued_key(self) -> tuple[int, str] | None:
        return self._continued_key

    def is_own_observation(self, observation: ForegroundObservation) -> bool:
        return observation.pid == self._own_pid

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
        if executable_name(path) not in {"chrome.exe", "msedge.exe"}:
            self._website_current_key = None
            self._last_non_browser_window_hwnd = observation.hwnd

        if self._continued_key is not None and key != self._continued_key:
            self._continued_key = None
            self._continued_prompt = None

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
            target_key=path,
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
        key = (
            prompt.target_hwnd,
            prompt.target_key or normalize_windows_path(prompt.executable_path),
        )
        if decision is PolicyDecision.CONTINUE:
            self._continued_key = key
            self._continued_prompt = prompt
            activate_hwnd = prompt.target_hwnd
        else:
            self._continued_key = None
            self._continued_prompt = None
            activate_hwnd = prompt.return_hwnd
        return DecisionResult(prompt, decision, activate_hwnd)

    def cancel_prompt(self) -> None:
        """Discard a prompt created while selecting an application."""
        self._prompt = None

    def observe_website(
        self,
        *,
        context_id: str,
        foreground_epoch: int,
        revision: int,
        hwnd: int,
        pid: int,
        browser_name: str,
        executable_path: str,
        domain: str,
        now: datetime,
    ) -> PolicyUpdate:
        """Evaluate one resolved browser hostname against active site rules."""
        normalized = normalize_domain(domain)
        marker = (context_id, foreground_epoch, revision, hwnd, normalized)
        if getattr(self, "_website_marker", None) == marker:
            return PolicyUpdate()
        self._website_marker = marker
        key = (hwnd, normalized)
        self._website_current_key = key
        if self._continued_key is not None and self._continued_key != key:
            self._continued_key = None
            self._continued_prompt = None
        active = active_schedules_at(self._configuration.schedules, now)
        allowed = not active or self._is_website_allowed(normalized, active)
        if allowed:
            dismiss = self._prompt is not None
            self._prompt = None
            self._last_allowed_hwnd = hwnd
            return PolicyUpdate(dismiss_prompt=dismiss, active_schedules=active)
        if key == self._continued_key:
            return PolicyUpdate(active_schedules=active)
        if (
            self._prompt is not None
            and self._prompt.target_type is TargetType.WEBSITE
            and self._prompt.target_hwnd == hwnd
            and self._prompt.target_key == normalized
        ):
            # Repeated tab/update events for the same unresolved site must not
            # replace the prompt ID; its decision may already be in flight.
            return PolicyUpdate(active_schedules=active)
        prompt = AttentionPrompt(
            id=str(uuid.uuid4()),
            target_hwnd=hwnd,
            target_pid=pid,
            application_name=browser_name,
            executable_path=executable_path,
            return_hwnd=self._last_non_browser_window_hwnd,
            schedule_ids=tuple(schedule.id for schedule in active),
            schedule_names=tuple(schedule.name for schedule in active),
            target_type=TargetType.WEBSITE,
            target_key=normalized,
        )
        dismiss = self._prompt is not None
        self._prompt = prompt
        return PolicyUpdate(
            prompt=prompt,
            dismiss_prompt=dismiss,
            active_schedules=active,
        )

    def _is_website_allowed(self, domain: str, schedules: tuple[Schedule, ...]) -> bool:
        active_ids = {schedule.id for schedule in schedules}
        return any(
            entry.enabled
            and (entry.schedule_id is None or entry.schedule_id in active_ids)
            and (
                domain == entry.domain
                or (entry.include_subdomains and domain.endswith("." + entry.domain))
            )
            for entry in self._configuration.websites
        )

    def pause_for_system_unavailability(self) -> bool:
        """Dismiss prompts across lock/sleep while preserving continued consent."""
        dismiss = self._prompt is not None
        self._prompt = None
        if self._continued_key is None:
            self._current_key = None
            self._continued_prompt = None
        return dismiss

    def invalidate_website_context(self, *, preserve_continued: bool = False) -> bool:
        """Discard stale website prompts, optionally preserving same-entry consent."""
        dismiss = (
            self._prompt is not None and self._prompt.target_type is TargetType.WEBSITE
        )
        if dismiss:
            self._prompt = None
        if not preserve_continued and (
            self._continued_prompt is not None
            and self._continued_prompt.target_type is TargetType.WEBSITE
        ):
            self._continued_key = None
            self._continued_prompt = None
        self._website_marker = None
        self._website_current_key = None
        return dismiss

    def refresh(self, now: datetime) -> PolicyUpdate:
        """Re-evaluate schedule boundaries without inventing a foreground entry."""
        active = active_schedules_at(self._configuration.schedules, now)
        if active:
            dismiss = self._prompt is not None and self._prompt_allowed(
                self._prompt, active
            )
            if dismiss:
                self._prompt = None
            if self._continued_prompt is not None and self._prompt_allowed(
                self._continued_prompt, active
            ):
                self._continued_key = None
                self._continued_prompt = None
            updated = None
            if self._prompt is not None and (
                self._prompt.schedule_ids != tuple(s.id for s in active)
                or self._prompt.schedule_names != tuple(s.name for s in active)
            ):
                self._prompt = replace(
                    self._prompt,
                    schedule_ids=tuple(s.id for s in active),
                    schedule_names=tuple(s.name for s in active),
                )
                updated = self._prompt
            return PolicyUpdate(
                prompt=updated, dismiss_prompt=dismiss, active_schedules=active
            )
        dismiss = self._prompt is not None
        self._prompt = None
        self._continued_key = None
        self._continued_prompt = None
        return PolicyUpdate(dismiss_prompt=dismiss, active_schedules=())

    def follow_up(
        self, foreground_seconds: int, now: datetime
    ) -> AttentionPrompt | None:
        """Create a follow-up only for the still-current continued context."""
        previous = self._continued_prompt
        if (
            previous is None
            or self._continued_key is None
            or (
                self._website_current_key
                if previous.target_type is TargetType.WEBSITE
                else self._current_key
            )
            != self._continued_key
            or self._prompt is not None
        ):
            return None
        active = active_schedules_at(self._configuration.schedules, now)
        if not active:
            self._continued_key = None
            self._continued_prompt = None
            return None
        prompt = AttentionPrompt(
            id=str(uuid.uuid4()),
            target_hwnd=previous.target_hwnd,
            target_pid=previous.target_pid,
            application_name=previous.application_name,
            executable_path=previous.executable_path,
            return_hwnd=previous.return_hwnd,
            schedule_ids=tuple(schedule.id for schedule in active),
            schedule_names=tuple(schedule.name for schedule in active),
            foreground_seconds=foreground_seconds,
            target_type=previous.target_type,
            target_key=previous.target_key,
        )
        self._prompt = prompt
        return prompt

    def _is_allowed(self, path: str, schedules: tuple[Schedule, ...]) -> bool:
        active_ids = {schedule.id for schedule in schedules}
        return any(
            entry.enabled
            and entry.identity.executable_path is not None
            and normalize_windows_path(entry.identity.executable_path) == path
            and (entry.schedule_id is None or entry.schedule_id in active_ids)
            for entry in self._configuration.applications
        )

    def _prompt_allowed(
        self, prompt: AttentionPrompt, schedules: tuple[Schedule, ...]
    ) -> bool:
        if prompt.target_type is TargetType.WEBSITE:
            return self._is_website_allowed(prompt.target_key or "", schedules)
        path = normalize_windows_path(prompt.executable_path)
        return self._is_system_path(path) or self._is_allowed(path, schedules)

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
