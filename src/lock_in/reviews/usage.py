"""Monotonic measurement, independent of reminder intervals and overlapping plans."""

from datetime import datetime, timedelta

from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)
from lock_in.reviews.models import UsageRecord
from lock_in.rules.application_policy import (
    SYSTEM_EXECUTABLES,
    FocusConfiguration,
    active_schedules_at,
    executable_name,
    normalize_windows_path,
)


class UsageTracker:
    def __init__(self, own_pid: int) -> None:
        self.configuration = FocusConfiguration()
        self._own_pid = own_pid
        self._application: ForegroundObservation | None = None
        self._domain: str | None = None
        self._available = True
        self._previous: tuple[datetime, int] | None = None

    def observe(self, observation: ForegroundObservation) -> None:
        self._application = observation if self._available else None
        self._domain = None

    def website(self, domain: str | None, hwnd: int) -> None:
        app = self._application
        if app is not None and app.hwnd == hwnd and app.pid != self._own_pid:
            self._domain = domain

    def availability(self, available: bool) -> None:
        self._available = available
        self._application = None
        self._domain = None
        self._previous = None

    def advance(self, now: datetime, monotonic_ms: int) -> tuple[UsageRecord, ...]:
        previous = self._previous
        if previous is not None and monotonic_ms < previous[1]:
            return ()
        self._previous = (now, monotonic_ms)
        if previous is None or not self._available or self._application is None:
            return ()
        start, previous_ms = previous
        elapsed = monotonic_ms - previous_ms
        # A long scheduling gap is unverified (for example a missed sleep event).
        if not 0 < elapsed <= 5000:
            return ()
        records = []
        # Split at whole seconds, including midnight and UI schedule boundaries.
        # The monotonic clock is the sole duration source, even after clock edits.
        while elapsed > 0:
            duration = min(elapsed, 1000 - start.microsecond // 1000)
            active = active_schedules_at(self.configuration.schedules, start)
            if active:
                records.append(
                    UsageRecord(
                        start.date(),
                        start,
                        duration,
                        duration if self._outside(active) else 0,
                    )
                )
            elapsed -= duration
            start += timedelta(milliseconds=duration)
        return tuple(records)

    def _outside(self, active) -> bool:
        app = self._application
        if (
            app is None
            or app.pid == self._own_pid
            or app.status is not ResolutionStatus.IDENTIFIED
            or not app.executable_path
        ):
            return False
        active_ids = {item.id for item in active}
        path = normalize_windows_path(app.executable_path)
        name = executable_name(path)
        if name in {"chrome.exe", "msedge.exe"}:
            if self._domain is None:
                return False
            return not any(
                entry.enabled
                and (entry.schedule_id is None or entry.schedule_id in active_ids)
                and (
                    self._domain == entry.domain
                    or (
                        entry.include_subdomains
                        and self._domain.endswith("." + entry.domain)
                    )
                )
                for entry in self.configuration.websites
            )
        if name in SYSTEM_EXECUTABLES:
            return False
        return not any(
            entry.enabled
            and (entry.schedule_id is None or entry.schedule_id in active_ids)
            and entry.identity.executable_path
            and normalize_windows_path(entry.identity.executable_path) == path
            for entry in self.configuration.applications
        )
