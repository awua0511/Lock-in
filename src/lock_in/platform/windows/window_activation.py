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
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._kernel32.GetCurrentThreadId.argtypes = []
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        self._user32.AttachThreadInput.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL

    def activate(self, hwnd: int | None) -> bool:
        if not hwnd or not self._user32.IsWindow(hwnd):
            return False
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, SW_RESTORE)
        if self._user32.SetForegroundWindow(hwnd):
            return True

        # SetForegroundWindow is restricted by Windows' foreground lock. When
        # the user just acted on Lock-In's prompt, temporarily share input with
        # the foreground and target threads and verify that activation worked.
        foreground_hwnd = self._user32.GetForegroundWindow()
        current_thread = int(self._kernel32.GetCurrentThreadId())
        target_thread = int(self._user32.GetWindowThreadProcessId(hwnd, None))
        foreground_thread = (
            int(self._user32.GetWindowThreadProcessId(foreground_hwnd, None))
            if foreground_hwnd
            else 0
        )
        attached: list[int] = []
        for thread_id in dict.fromkeys((foreground_thread, target_thread)):
            if thread_id and thread_id != current_thread:
                if self._user32.AttachThreadInput(current_thread, thread_id, True):
                    attached.append(thread_id)
        try:
            self._user32.BringWindowToTop(hwnd)
            activated = bool(self._user32.SetForegroundWindow(hwnd))
            return activated or self._user32.GetForegroundWindow() == hwnd
        finally:
            for thread_id in reversed(attached):
                self._user32.AttachThreadInput(current_thread, thread_id, False)
