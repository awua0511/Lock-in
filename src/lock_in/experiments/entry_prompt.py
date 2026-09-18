"""Interactive Windows entry-prompt prototype for Experiment 2."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import sys
import time
import tkinter as tk
from collections.abc import Sequence
from datetime import datetime
from tkinter import ttk

from lock_in.platform.windows.foreground_monitor import (
    ForegroundMonitor,
    ForegroundObservation,
    Win32Api,
)
from lock_in.prompts.entry_policy import (
    EntryPromptPolicy,
    PromptDecision,
    PromptRequest,
)

if os.name == "nt":
    from ctypes import wintypes


SW_RESTORE = 9


class WindowActivator:
    """Small Win32 adapter for restoring an existing top-level window."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Experiment 2 requires Windows.")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

    def activate(self, hwnd: int | None) -> bool:
        if not hwnd or not self._user32.IsWindow(hwnd):
            return False
        if self._user32.IsIconic(hwnd):
            self._user32.ShowWindow(hwnd, SW_RESTORE)
        return bool(self._user32.SetForegroundWindow(hwnd))


class PromptPrototype:
    """Bridge monitor events into the Tk main thread and render one prompt."""

    def __init__(self, root: tk.Tk, allowed_paths: list[str], *, as_json: bool) -> None:
        self._root = root
        self._root.withdraw()
        self._as_json = as_json
        self._policy = EntryPromptPolicy(allowed_paths)
        self._activator = WindowActivator()
        self._events: queue.Queue[ForegroundObservation] = queue.Queue()
        self._monitor = ForegroundMonitor(Win32Api(), self._events.put)
        self._dialog: tk.Toplevel | None = None
        self._request: PromptRequest | None = None
        self._stopping = False

    def start(self) -> None:
        self._monitor.start()
        self._root.after(25, self._drain_events)

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._monitor.stop()
        if self._dialog is not None:
            self._dialog.destroy()
        self._root.quit()

    def _drain_events(self) -> None:
        if self._stopping:
            return
        while True:
            try:
                observation = self._events.get_nowait()
            except queue.Empty:
                break
            had_prompt = self._policy.active_prompt is not None
            request = self._policy.observe(observation)
            if request is not None:
                self._show_prompt(request)
            elif had_prompt and self._policy.active_prompt is None:
                self._dismiss_stale_prompt()
        self._root.after(25, self._drain_events)

    def _dismiss_stale_prompt(self) -> None:
        self._request = None
        if self._dialog is not None:
            self._dialog.destroy()
            self._dialog = None

    def _show_prompt(self, request: PromptRequest) -> None:
        if self._dialog is not None:
            self._dialog.destroy()

        self._request = request
        dialog = tk.Toplevel(self._root)
        self._dialog = dialog
        dialog.title("Lock-In focus check")
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.protocol("WM_DELETE_WINDOW", self._continue)

        frame = ttk.Frame(dialog, padding=24)
        frame.grid()
        ttk.Label(
            frame,
            text="This application is outside your experiment allowlist.",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame,
            text=f"Currently open: {request.application_name}",
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 4))
        ttk.Label(
            frame,
            text="Do you still want to open it?",
            font=("Segoe UI", 10),
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 18))

        return_button = ttk.Button(frame, text="Return", command=self._return)
        return_button.grid(row=3, column=0, padx=(0, 8), sticky="ew")
        if request.return_hwnd is None:
            return_button.state(["disabled"])
        ttk.Button(frame, text="Continue anyway", command=self._continue).grid(
            row=3,
            column=1,
            sticky="ew",
        )
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        dialog.update_idletasks()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        x = (dialog.winfo_screenwidth() - width) // 2
        y = (dialog.winfo_screenheight() - height) // 3
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        return_button.focus_set()
        if request.return_hwnd is not None:
            dialog.bind("<Escape>", lambda _event: self._return())

        self._emit(
            "prompt_shown",
            request,
            returnAvailable=request.return_hwnd is not None,
        )

    def _return(self) -> None:
        self._finish(PromptDecision.RETURN)

    def _continue(self) -> None:
        self._finish(PromptDecision.CONTINUE)

    def _finish(self, decision: PromptDecision) -> None:
        request = self._request
        result = self._policy.decide(decision)
        self._request = None
        if self._dialog is not None:
            self._dialog.destroy()
            self._dialog = None
        if request is None or result is None:
            return

        activated = self._activator.activate(result.activate_hwnd)
        self._emit(
            "decision",
            request,
            decision=decision.value,
            activationSucceeded=activated,
        )

    def _emit(self, event: str, request: PromptRequest, **extra: object) -> None:
        payload = {
            "event": event,
            "observedAt": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonicMs": time.monotonic_ns() // 1_000_000,
            "targetHwnd": request.target_hwnd,
            "targetPid": request.target_pid,
            "applicationName": request.application_name,
            **extra,
        }
        if self._as_json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
        else:
            fields = [f"{key}={value}" for key, value in payload.items()]
            print("\t".join(fields), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Lock-In entry prompts and foreground restoration.",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="EXE_PATH",
        help="Allow one executable path. Repeat for multiple applications.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON lines.")
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

    root = tk.Tk()
    prototype = PromptPrototype(root, args.allow, as_json=args.json)
    root.protocol("WM_DELETE_WINDOW", prototype.stop)
    try:
        prototype.start()
        if args.duration is not None:
            root.after(round(args.duration * 1000), prototype.stop)
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        prototype.stop()
        root.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
