"""Non-blocking application entry decision prompt."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from lock_in.rules.application_policy import AttentionPrompt, PolicyDecision


class AttentionPromptDialog(QDialog):
    def __init__(
        self,
        prompt: AttentionPrompt,
        decide: Callable[[str, PolicyDecision], None],
    ) -> None:
        super().__init__()
        self._prompt = prompt
        self._decide = decide
        self._resolved = False
        self.setWindowTitle("Lock-In focus check")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        heading = QLabel("This application is outside your current work allowlist.")
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(QLabel(f"Currently open: {prompt.application_name}"))
        layout.addWidget(QLabel(f"Work schedule: {', '.join(prompt.schedule_names)}"))
        layout.addWidget(QLabel("Do you still want to continue?"))

        buttons = QHBoxLayout()
        return_button = QPushButton("Return to previous window")
        return_button.setEnabled(prompt.return_hwnd is not None)
        return_button.clicked.connect(lambda: self._finish(PolicyDecision.RETURN))
        continue_button = QPushButton("Continue anyway")
        continue_button.clicked.connect(lambda: self._finish(PolicyDecision.CONTINUE))
        buttons.addWidget(return_button)
        buttons.addWidget(continue_button)
        layout.addLayout(buttons)
        continue_button.setFocus()

    def dismiss_stale(self) -> None:
        self._resolved = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._resolved:
            self._finish(PolicyDecision.CONTINUE)
        event.accept()

    def _finish(self, decision: PolicyDecision) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._decide(self._prompt.id, decision)
        self.close()
