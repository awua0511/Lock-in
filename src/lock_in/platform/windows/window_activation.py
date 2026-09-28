"""Best-effort activation of an existing ordinary Windows window."""

from __future__ import annotations

import ctypes
import os

if os.name == "nt":
    from ctypes import wintypes

SW_RESTORE = 9


class WindowActivator:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Window activation is available only on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindowAsync.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND

    def activate(self, hwnd: int | None) -> bool:
        if not hwnd or not self._user32.IsWindow(hwnd):
            return False
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindowAsync(hwnd, SW_RESTORE)
        # Never attach input queues or synchronously restore another process:
        # an unresponsive target could otherwise stall the decision dispatcher.
        # Respect foreground restrictions and report a best-effort failure.
        return bool(
            self._user32.SetForegroundWindow(hwnd)
            or self._user32.GetForegroundWindow() == hwnd
        )
