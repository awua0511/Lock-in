"""Minimal Milestone 1 settings window placeholder."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    def __init__(self, *, hide_on_close: bool) -> None:
        super().__init__()
        self._hide_on_close = hide_on_close
        self.setWindowTitle("Lock-In")
        self.resize(480, 240)
        label = QLabel(
            "Lock-In is running.\n\n"
            "Schedules and allowlists arrive in later milestones."
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(label)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._hide_on_close:
            self.hide()
            event.ignore()
            return
        event.accept()
