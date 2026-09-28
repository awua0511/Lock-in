"""Non-blocking application entry decision prompt."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from lock_in.domain.models import TargetType
from lock_in.rules.application_policy import AttentionPrompt, PolicyDecision
from lock_in.ui.theme import text_label


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
        self._decision_pending = False
        self.setWindowTitle("Lock-In focus check")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumWidth(460)
        self.setMaximumWidth(620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(16)
        layout.addWidget(text_label("A MOMENT TO CHOOSE", "eyebrow"))
        if prompt.foreground_seconds:
            target_label = (
                "website" if prompt.target_type is TargetType.WEBSITE else "application"
            )
            heading_text = (
                f"You have continued in this {target_label} for "
                f"{prompt.foreground_seconds} foreground seconds."
            )
        elif prompt.target_type is TargetType.WEBSITE:
            heading_text = "This website is outside your current work allowlist."
        else:
            heading_text = "This application is outside your current work allowlist."
        heading = text_label(heading_text)
        heading.setStyleSheet("font-size: 17pt; font-weight: 600; color: #183a3c;")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        if prompt.target_type is TargetType.WEBSITE:
            layout.addWidget(text_label(f"Website: {prompt.target_key or 'unknown'}"))
            layout.addWidget(text_label(f"Browser: {prompt.application_name}"))
        else:
            layout.addWidget(text_label(f"Currently open: {prompt.application_name}"))
        layout.addWidget(
            text_label(f"Work schedule: {', '.join(prompt.schedule_names)}")
        )
        layout.addWidget(
            text_label("Your work period stays active. The choice is yours.")
        )

        buttons = QHBoxLayout()
        self._buttons = []
        if prompt.target_type is TargetType.APPLICATION:
            return_button = QPushButton("Return to previous window")
            return_button.setEnabled(prompt.return_hwnd is not None)
            return_button.clicked.connect(lambda: self._finish(PolicyDecision.RETURN))
            buttons.addWidget(return_button)
            self._buttons.append(return_button)
        continue_button = QPushButton("Continue anyway")
        continue_button.setProperty("variant", "primary")
        continue_button.clicked.connect(lambda: self._finish(PolicyDecision.CONTINUE))
        self._buttons.append(continue_button)
        buttons.addWidget(continue_button)
        layout.addLayout(buttons)
        continue_button.setFocus()

    def dismiss_stale(self) -> None:
        self._resolved = True
        self._decision_pending = False
        self.close()

    def reject(self) -> None:
        # Escape invokes QDialog.reject directly, bypassing closeEvent.
        if not self._resolved:
            self._finish(PolicyDecision.CONTINUE)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._decision_pending:
            event.ignore()
            return
        if not self._resolved:
            self._finish(PolicyDecision.CONTINUE)
            event.ignore()
            return
        event.accept()

    def _finish(self, decision: PolicyDecision) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._decision_pending = True
        for button in self._buttons:
            button.setEnabled(False)
        self._decide(self._prompt.id, decision)
