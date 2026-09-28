"""Qt native-event adapter for Windows lock and power transitions."""

from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
WTS_SESSION_LOCK = 0x0007
WTS_SESSION_UNLOCK = 0x0008
NOTIFY_FOR_THIS_SESSION = 0

AvailabilitySink = Callable[[bool, str, int], None]


class SystemAvailability:
    """Sleep and session lock are independent; waking need not unlock Windows."""

    def __init__(self) -> None:
        self.locked = False
        self.suspended = False
        self.ending = False
        self.available = True

    def consume(self, message: int, wparam: int) -> tuple[bool, str] | None:
        decoded = decode_system_message(message, wparam)
        if message == WM_ENDSESSION:
            self.ending = bool(wparam)
            reason = "system_shutdown" if wparam else "shutdown_cancelled"
        elif decoded is None:
            return None
        else:
            _, reason = decoded
            if reason == "session_lock":
                self.locked = True
            elif reason == "session_unlock":
                self.locked = False
            elif reason == "system_suspend":
                self.suspended = True
            elif reason == "system_resume":
                self.suspended = False
            elif reason == "system_shutdown":
                self.ending = True
        available = not (self.locked or self.suspended or self.ending)
        if available == self.available:
            return None
        self.available = available
        return available, reason


def decode_system_message(message: int, wparam: int) -> tuple[bool, str] | None:
    if message == WM_WTSSESSION_CHANGE:
        if wparam == WTS_SESSION_LOCK:
            return False, "session_lock"
        if wparam == WTS_SESSION_UNLOCK:
            return True, "session_unlock"
    if message == WM_POWERBROADCAST:
        if wparam == PBT_APMSUSPEND:
            return False, "system_suspend"
        if wparam in {PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC}:
            return True, "system_resume"
    if message == WM_QUERYENDSESSION:
        return False, "system_shutdown"
    return None


class WindowsSystemEventFilter(QAbstractNativeEventFilter):
    """Publish availability changes without doing work in the native callback."""

    def __init__(self, window_handle: int, sink: AvailabilitySink) -> None:
        super().__init__()
        self._window_handle = window_handle
        self._sink = sink
        self._registered = False
        self._availability = SystemAvailability()
        if os.name == "nt":
            from ctypes import wintypes

            register = ctypes.windll.wtsapi32.WTSRegisterSessionNotification
            register.argtypes = [wintypes.HWND, wintypes.DWORD]
            register.restype = wintypes.BOOL
            self._registered = bool(register(window_handle, NOTIFY_FOR_THIS_SESSION))
        QCoreApplication.instance().installNativeEventFilter(self)  # type: ignore[union-attr]

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        del event_type
        if os.name != "nt":
            return False, 0
        from ctypes import wintypes

        native = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
        decoded = self._availability.consume(int(native.message), int(native.wParam))
        if decoded is None:
            return False, 0
        available, reason = decoded
        self._sink(available, reason, time.monotonic_ns() // 1_000_000)
        return False, 0

    def close(self) -> None:
        application = QCoreApplication.instance()
        if application is not None:
            application.removeNativeEventFilter(self)
        if self._registered and os.name == "nt":
            from ctypes import wintypes

            unregister = ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification
            unregister.argtypes = [wintypes.HWND]
            unregister.restype = wintypes.BOOL
            unregister(self._window_handle)
        self._registered = False
