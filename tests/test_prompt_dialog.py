from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from lock_in.domain.models import TargetType
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
    assert dialog._decision_pending
    dialog.dismiss_stale()
    assert not dialog._decision_pending


def test_continue_waits_for_decision_ack_before_closing() -> None:
    _ = QApplication.instance() or QApplication([])
    decisions = []
    dialog = AttentionPromptDialog(
        _prompt(), lambda prompt_id, decision: decisions.append((prompt_id, decision))
    )
    dialog.show()
    buttons = dialog.findChildren(QPushButton)

    buttons[-1].click()

    assert decisions == [("prompt-1", PolicyDecision.CONTINUE)]
    assert dialog.isVisible()
    assert all(not button.isEnabled() for button in buttons)
    dialog.dismiss_stale()
    assert not dialog.isVisible()


def test_stale_prompt_dismissal_makes_no_decision() -> None:
    _ = QApplication.instance() or QApplication([])
    decisions = []
    dialog = AttentionPromptDialog(
        _prompt(), lambda prompt_id, decision: decisions.append((prompt_id, decision))
    )

    dialog.dismiss_stale()

    assert decisions == []


def test_website_prompt_does_not_offer_unavailable_return_action() -> None:
    _ = QApplication.instance() or QApplication([])
    website_prompt = replace(
        _prompt(), target_type=TargetType.WEBSITE, target_key="youtube.com"
    )
    dialog = AttentionPromptDialog(website_prompt, lambda _prompt_id, _decision: None)

    assert [button.text() for button in dialog.findChildren(QPushButton)] == [
        "Continue anyway"
    ]


def test_escape_submits_continue_and_waits_for_ack():
    _ = QApplication.instance() or QApplication([])
    decisions = []
    dialog = AttentionPromptDialog(
        _prompt(), lambda _id, decision: decisions.append(decision)
    )
    dialog.show()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert decisions == [PolicyDecision.CONTINUE]
    assert dialog.isVisible()
    dialog.dismiss_stale()
    assert not dialog.isVisible()
