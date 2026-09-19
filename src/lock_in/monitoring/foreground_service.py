"""Production lifecycle adapter around the validated WinEvent monitor."""

from __future__ import annotations

from collections.abc import Callable

from lock_in.platform.windows.foreground_monitor import (
    ForegroundMonitor,
    ForegroundObservation,
    Win32Api,
)


class ForegroundMonitoringService:
    name = "foreground_monitor"

    def __init__(
        self,
        sink: Callable[[ForegroundObservation], None],
        *,
        monitor: ForegroundMonitor | None = None,
    ) -> None:
        self._monitor = monitor or ForegroundMonitor(Win32Api(), sink)

    def start(self) -> None:
        self._monitor.start()

    def stop(self, timeout: float) -> None:
        self._monitor.stop(timeout)
