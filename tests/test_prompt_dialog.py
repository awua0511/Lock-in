from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from lock_in.rules.application_policy import AttentionPrompt, PolicyDecision
from lock_in.ui.prompt_dialog import AttentionPromptDialog


def _prompt() -> AttentionPrompt:
    return AttentionPrompt(
        id="prompt-1",
        target_hwnd=20,
        target_pid=200,
        application_name="Steam",
        executable_path=r"C:\Games\Steam.exe",
        return_hwnd=10,
        schedule_ids=("schedule-1",),
        schedule_names=("Focus",),
    )


def test_closing_prompt_is_an_explicit_continue() -> None:
    _ = QApplication.instance() or QApplication([])
    decisions = []
    dialog = AttentionPromptDialog(
        _prompt(), lambda prompt_id, decision: decisions.append((prompt_id, decision))
    )

    dialog.close()

    assert decisions == [("prompt-1", PolicyDecision.CONTINUE)]


def test_stale_prompt_dismissal_makes_no_decision() -> None:
    _ = QApplication.instance() or QApplication([])
    decisions = []
    dialog = AttentionPromptDialog(
        _prompt(), lambda prompt_id, decision: decisions.append((prompt_id, decision))
    )

    dialog.dismiss_stale()

    assert decisions == []
