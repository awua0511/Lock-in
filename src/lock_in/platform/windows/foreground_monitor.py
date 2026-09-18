"""Event-driven foreground application monitor for Windows.

Experiment 1 deliberately uses only the Python standard library so Win32
behavior can be validated before UI and application dependencies are added.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import ntpath
import os
import queue
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

if os.name == "nt":
    from ctypes import wintypes


EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
ERROR_INVALID_PARAMETER = 87
MAX_IMAGE_PATH_CHARS = 32_768


class ResolutionStatus(StrEnum):
    """Result of resolving a foreground window to an executable."""

    IDENTIFIED = "identified"
    NO_FOREGROUND_WINDOW = "no_foreground_window"
    INVALID_WINDOW = "invalid_window"
    WINDOW_WITHOUT_PROCESS = "window_without_process"
    PROCESS_ACCESS_DENIED = "process_access_denied"
    PROCESS_EXITED = "process_exited"
    PATH_QUERY_FAILED = "path_query_failed"
    CALLBACK_ERROR = "callback_error"


class Win32ResolutionError(RuntimeError):
    """A Win32 failure with a stable status and native error code."""

    def __init__(
        self,
        status: ResolutionStatus,
        message: str,
        error_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code


@dataclass(frozen=True, slots=True)
class ForegroundObservation:
    """One resolved foreground-window observation."""

    sequence: int
    observed_at: str
    monotonic_ms: int
    hwnd: int | None
    pid: int | None
    application_name: str | None
    executable_path: str | None
    status: ResolutionStatus
    error_code: int | None = None
    error_message: str | None = None
    window_title: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["status"] = self.status.value
        return result


class ForegroundApi(Protocol):
    """Small API surface needed by the pure resolver."""

    def get_foreground_window(self) -> int: ...

    def is_window(self, hwnd: int) -> bool: ...

    def get_window_process_id(self, hwnd: int) -> int: ...

    def query_process_image_path(self, pid: int) -> str: ...

    def get_window_title(self, hwnd: int) -> str | None: ...


Clock = Callable[[], tuple[str, int]]


def current_clock() -> tuple[str, int]:
    """Return an ISO wall-clock timestamp and monotonic milliseconds."""

    return (
        datetime.now().astimezone().isoformat(timespec="milliseconds"),
        time.monotonic_ns() // 1_000_000,
    )


def application_name_from_path(path: str) -> str | None:
    """Derive a diagnostic name from a Windows executable path."""

    filename = ntpath.basename(path.rstrip("\\/"))
    if not filename:
        return None
    name, _ = ntpath.splitext(filename)
    return name or filename


class ForegroundResolver:
    """Resolve HWND values without owning hook or thread lifecycle."""

    def __init__(
        self,
        api: ForegroundApi,
        *,
        include_window_title: bool = False,
        clock: Clock = current_clock,
    ) -> None:
        self._api = api
        self._include_window_title = include_window_title
        self._clock = clock

    def resolve(self, hwnd: int, sequence: int) -> ForegroundObservation:
        observed_at, monotonic_ms = self._clock()
        normalized_hwnd = int(hwnd) if hwnd else None

        if not normalized_hwnd:
            return ForegroundObservation(
                sequence,
                observed_at,
                monotonic_ms,
                None,
                None,
                None,
                None,
                ResolutionStatus.NO_FOREGROUND_WINDOW,
            )

        if not self._api.is_window(normalized_hwnd):
            return ForegroundObservation(
                sequence,
                observed_at,
                monotonic_ms,
                normalized_hwnd,
                None,
                None,
                None,
                ResolutionStatus.INVALID_WINDOW,
            )

        pid = self._api.get_window_process_id(normalized_hwnd)
        if not pid:
            return ForegroundObservation(
                sequence,
                observed_at,
                monotonic_ms,
                normalized_hwnd,
                None,
                None,
                None,
                ResolutionStatus.WINDOW_WITHOUT_PROCESS,
            )

        title = (
            self._api.get_window_title(normalized_hwnd)
            if self._include_window_title
            else None
        )
        try:
            path = self._api.query_process_image_path(pid)
        except Win32ResolutionError as error:
            return ForegroundObservation(
                sequence=sequence,
                observed_at=observed_at,
                monotonic_ms=monotonic_ms,
                hwnd=normalized_hwnd,
                pid=pid,
                application_name=None,
                executable_path=None,
                status=error.status,
                error_code=error.error_code,
                error_message=str(error),
                window_title=title,
            )

        return ForegroundObservation(
            sequence=sequence,
            observed_at=observed_at,
            monotonic_ms=monotonic_ms,
            hwnd=normalized_hwnd,
            pid=pid,
            application_name=application_name_from_path(path),
            executable_path=path,
            status=ResolutionStatus.IDENTIFIED,
            window_title=title,
        )


class Win32Api:
    """Thin ctypes wrapper around the Win32 APIs used by Experiment 1."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("The foreground monitor is available only on Windows.")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.GetCurrentThreadId.argtypes = []
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.GetMessageW.restype = ctypes.c_int
        self._user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.PeekMessageW.restype = wintypes.BOOL
        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.TranslateMessage.restype = wintypes.BOOL
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        self._user32.DispatchMessageW.restype = wintypes.LPARAM
        self._user32.PostThreadMessageW.argtypes = [
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.PostThreadMessageW.restype = wintypes.BOOL

    def get_foreground_window(self) -> int:
        return int(self._user32.GetForegroundWindow() or 0)

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindow(hwnd))

    def get_window_process_id(self, hwnd: int) -> int:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def query_process_image_path(self, pid: int) -> str:
        process = self._kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not process:
            error_code = ctypes.get_last_error()
            status = {
                ERROR_ACCESS_DENIED: ResolutionStatus.PROCESS_ACCESS_DENIED,
                ERROR_INVALID_PARAMETER: ResolutionStatus.PROCESS_EXITED,
            }.get(error_code, ResolutionStatus.PATH_QUERY_FAILED)
            raise Win32ResolutionError(
                status,
                f"OpenProcess failed for PID {pid}",
                error_code,
            )

        try:
            buffer = ctypes.create_unicode_buffer(MAX_IMAGE_PATH_CHARS)
            length = wintypes.DWORD(len(buffer))
            succeeded = self._kernel32.QueryFullProcessImageNameW(
                process,
                0,
                buffer,
                ctypes.byref(length),
            )
            if not succeeded:
                error_code = ctypes.get_last_error()
                status = (
                    ResolutionStatus.PROCESS_EXITED
                    if error_code == ERROR_INVALID_PARAMETER
                    else ResolutionStatus.PATH_QUERY_FAILED
                )
                raise Win32ResolutionError(
                    status,
                    f"QueryFullProcessImageNameW failed for PID {pid}",
                    error_code,
                )
            return buffer.value[: length.value]
        finally:
            self._kernel32.CloseHandle(process)

    def get_window_title(self, hwnd: int) -> str | None:
        length = self._user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return None
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value[:copied] if copied > 0 else None

    def current_thread_id(self) -> int:
        return int(self._kernel32.GetCurrentThreadId())

    def ensure_message_queue(self) -> None:
        # A thread does not own a message queue until it calls a User32 message
        # function. Creating it before publishing the thread ID makes
        # PostThreadMessage(WM_QUIT) reliable during shutdown.
        message = wintypes.MSG()
        self._user32.PeekMessageW(
            ctypes.byref(message),
            None,
            0,
            0,
            PM_NOREMOVE,
        )

    def make_event_callback(self, callback: Callable[[int], None]):
        callback_type = ctypes.WINFUNCTYPE(
            None,
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.HWND,
            wintypes.LONG,
            wintypes.LONG,
            wintypes.DWORD,
            wintypes.DWORD,
        )

        def on_event(
            _hook,
            _event,
            hwnd,
            _object_id,
            _child_id,
            _event_thread,
            _event_time,
        ) -> None:
            callback(int(hwnd or 0))

        return callback_type(on_event)

    def install_foreground_hook(self, callback_pointer) -> int:
        self._user32.SetWinEventHook.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HMODULE,
            type(callback_pointer),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._user32.SetWinEventHook.restype = wintypes.HANDLE
        hook = self._user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            callback_pointer,
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
        if not hook:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "SetWinEventHook failed")
        return int(hook)

    def uninstall_hook(self, hook: int) -> None:
        self._user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        self._user32.UnhookWinEvent.restype = wintypes.BOOL
        self._user32.UnhookWinEvent(hook)

    def run_message_loop(self) -> None:
        message = wintypes.MSG()
        while True:
            result = int(self._user32.GetMessageW(ctypes.byref(message), None, 0, 0))
            if result == -1:
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "GetMessageW failed")
            if result == 0:
                return
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))

    def post_quit(self, thread_id: int) -> None:
        if not self._user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "PostThreadMessageW failed")


ObservationSink = Callable[[ForegroundObservation], None]


class ForegroundMonitor:
    """Own the hook thread and resolve events away from the callback."""

    def __init__(
        self,
        api: Win32Api,
        sink: ObservationSink,
        *,
        include_window_title: bool = False,
    ) -> None:
        self._api = api
        self._sink = sink
        self._resolver = ForegroundResolver(
            api,
            include_window_title=include_window_title,
        )
        self._events: queue.Queue[int | None] = queue.Queue()
        self._ready = threading.Event()
        self._hook_thread: threading.Thread | None = None
        self._resolver_thread: threading.Thread | None = None
        self._hook_thread_id: int | None = None
        self._startup_error: BaseException | None = None
        self._running = False
        self._sequence = 0

    def start(self, timeout: float = 5.0) -> None:
        if self._running:
            raise RuntimeError("ForegroundMonitor is already running")
        self._running = True
        self._resolver_thread = threading.Thread(
            target=self._resolver_loop,
            name="foreground-resolver",
            daemon=True,
        )
        self._hook_thread = threading.Thread(
            target=self._hook_loop,
            name="foreground-hook",
            daemon=True,
        )
        self._resolver_thread.start()
        self._hook_thread.start()

        if not self._ready.wait(timeout):
            self.stop()
            raise TimeoutError("Timed out while installing the foreground hook")
        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise RuntimeError("Could not start foreground monitoring") from error

    def stop(self, timeout: float = 5.0) -> None:
        if not self._running:
            return
        self._running = False
        if self._hook_thread_id is not None:
            try:
                self._api.post_quit(self._hook_thread_id)
            except OSError:
                pass
        if self._hook_thread is not None:
            self._hook_thread.join(timeout)
        self._events.put(None)
        if self._resolver_thread is not None:
            self._resolver_thread.join(timeout)
        self._hook_thread = None
        self._resolver_thread = None
        self._hook_thread_id = None

    def _hook_loop(self) -> None:
        hook: int | None = None
        callback_pointer = None
        try:
            self._api.ensure_message_queue()
            self._hook_thread_id = self._api.current_thread_id()
            callback_pointer = self._api.make_event_callback(self._events.put)
            hook = self._api.install_foreground_hook(callback_pointer)
            self._events.put(self._api.get_foreground_window())
        except BaseException as error:
            self._startup_error = error
            self._ready.set()
            return

        self._ready.set()
        try:
            self._api.run_message_loop()
        finally:
            if hook is not None:
                self._api.uninstall_hook(hook)
            _ = callback_pointer  # Keep callback alive until the hook is removed.

    def _resolver_loop(self) -> None:
        while True:
            hwnd = self._events.get()
            if hwnd is None:
                return
            self._sequence += 1
            try:
                observation = self._resolver.resolve(hwnd, self._sequence)
            except BaseException as error:
                observed_at, monotonic_ms = current_clock()
                observation = ForegroundObservation(
                    sequence=self._sequence,
                    observed_at=observed_at,
                    monotonic_ms=monotonic_ms,
                    hwnd=int(hwnd) if hwnd else None,
                    pid=None,
                    application_name=None,
                    executable_path=None,
                    status=ResolutionStatus.CALLBACK_ERROR,
                    error_message=f"{type(error).__name__}: {error}",
                )
            try:
                self._sink(observation)
            except BaseException:
                continue  # A diagnostic sink must not terminate monitoring.


def format_observation(observation: ForegroundObservation, *, as_json: bool) -> str:
    """Format an observation for console or machine-readable capture."""

    if as_json:
        return json.dumps(observation.to_dict(), ensure_ascii=False, sort_keys=True)

    hwnd = f"0x{observation.hwnd:016X}" if observation.hwnd is not None else "-"
    fields = [
        observation.observed_at,
        f"seq={observation.sequence}",
        f"status={observation.status.value}",
        f"hwnd={hwnd}",
        f"pid={observation.pid if observation.pid is not None else '-'}",
        f"app={observation.application_name or '-'}",
        f"path={observation.executable_path or '-'}",
    ]
    if observation.window_title is not None:
        fields.append(f"title={observation.window_title}")
    if observation.error_code is not None:
        fields.append(f"winerror={observation.error_code}")
    if observation.error_message:
        fields.append(f"error={observation.error_message}")
    return "\t".join(fields)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Observe foreground application changes using WinEvent hooks.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON lines.")
    parser.add_argument(
        "--include-window-title",
        action="store_true",
        help="Include potentially sensitive window titles.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Resolve the current foreground application and exit.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        metavar="SECONDS",
        help="Stop automatically after this many seconds.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.name != "nt":
        print("This experiment requires Windows.", file=sys.stderr)
        return 2
    if args.duration is not None and args.duration <= 0:
        print("--duration must be greater than zero.", file=sys.stderr)
        return 2

    api = Win32Api()
    resolver = ForegroundResolver(
        api,
        include_window_title=args.include_window_title,
    )
    if args.once:
        observation = resolver.resolve(api.get_foreground_window(), sequence=1)
        print(format_observation(observation, as_json=args.json), flush=True)
        return 0 if observation.status == ResolutionStatus.IDENTIFIED else 1

    def emit(observation: ForegroundObservation) -> None:
        print(format_observation(observation, as_json=args.json), flush=True)

    monitor = ForegroundMonitor(
        api,
        emit,
        include_window_title=args.include_window_title,
    )
    stop_requested = threading.Event()

    def request_stop(_signum=None, _frame=None) -> None:
        stop_requested.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    monitor.start()
    started = time.monotonic()
    try:
        while not stop_requested.wait(0.1):
            if (
                args.duration is not None
                and time.monotonic() - started >= args.duration
            ):
                break
    finally:
        monitor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
