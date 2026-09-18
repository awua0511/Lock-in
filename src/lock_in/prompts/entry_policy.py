"""Pure entry-prompt state machine used by Experiment 2.

The policy deliberately knows nothing about GUI toolkits or Win32 calls. It
decides when an entry prompt is required and which HWND should be restored
after the user makes a choice.
"""

from __future__ import annotations

import ntpath
import os
from dataclasses import dataclass
from enum import StrEnum

from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)


def normalize_windows_path(path: str) -> str:
    """Return a stable comparison key for an absolute Windows path."""

    return ntpath.normcase(ntpath.normpath(path.strip().strip('"')))


class PromptDecision(StrEnum):
    RETURN = "return"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class PromptRequest:
    target_hwnd: int
    target_pid: int
    application_name: str
    executable_path: str
    return_hwnd: int | None


@dataclass(frozen=True, slots=True)
class DecisionResult:
    decision: PromptDecision
    target_hwnd: int
    activate_hwnd: int | None


class EntryPromptPolicy:
    """Decide when one prompt is due for each disallowed foreground entry."""

    def __init__(
        self,
        allowed_paths: list[str] | tuple[str, ...],
        *,
        own_pid: int | None = None,
    ) -> None:
        self._allowed_paths = {
            normalize_windows_path(path) for path in allowed_paths if path.strip()
        }
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._current_external_hwnd: int | None = None
        self._last_allowed_hwnd: int | None = None
        self._prompt: PromptRequest | None = None
        self._continued_hwnd: int | None = None

    @property
    def active_prompt(self) -> PromptRequest | None:
        return self._prompt

    @property
    def last_allowed_hwnd(self) -> int | None:
        return self._last_allowed_hwnd

    def is_allowed(self, executable_path: str) -> bool:
        return normalize_windows_path(executable_path) in self._allowed_paths

    def observe(self, observation: ForegroundObservation) -> PromptRequest | None:
        """Consume a resolved foreground event and maybe request a prompt."""

        if observation.status != ResolutionStatus.IDENTIFIED:
            return None
        if observation.hwnd is None or observation.pid is None:
            return None
        if not observation.executable_path:
            return None
        if observation.pid == self._own_pid:
            return None

        hwnd = observation.hwnd
        path = observation.executable_path

        # Exact duplicate WinEvent notifications are not a new entry.
        if hwnd == self._current_external_hwnd:
            return None

        self._current_external_hwnd = hwnd
        if self._continued_hwnd is not None and hwnd != self._continued_hwnd:
            self._continued_hwnd = None

        if self.is_allowed(path):
            self._last_allowed_hwnd = hwnd
            self._prompt = None
            return None

        # Returning focus to a target after Continue is part of the same entry.
        if hwnd == self._continued_hwnd:
            self._continued_hwnd = None
            return None

        request = PromptRequest(
            target_hwnd=hwnd,
            target_pid=observation.pid,
            application_name=observation.application_name or "Unknown application",
            executable_path=path,
            return_hwnd=self._last_allowed_hwnd,
        )
        self._prompt = request
        return request

    def decide(self, decision: PromptDecision) -> DecisionResult | None:
        """Resolve the current prompt and return the HWND to activate."""

        request = self._prompt
        if request is None:
            return None
        self._prompt = None

        if decision == PromptDecision.CONTINUE:
            self._continued_hwnd = request.target_hwnd
            activate_hwnd = request.target_hwnd
        else:
            self._continued_hwnd = None
            activate_hwnd = request.return_hwnd

        return DecisionResult(
            decision=decision,
            target_hwnd=request.target_hwnd,
            activate_hwnd=activate_hwnd,
        )

    def cancel_prompt(self) -> None:
        """Drop a stale prompt after the target changes underneath it."""

        self._prompt = None
