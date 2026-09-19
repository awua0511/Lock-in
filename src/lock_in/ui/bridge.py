"""Qt signal bridge safe to call from the application event thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class QtUiBridge(QObject):
    show_main_window_signal = Signal()
    quit_signal = Signal()
    component_failure_signal = Signal(str)

    def show_main_window(self) -> None:
        self.show_main_window_signal.emit()

    def request_quit(self) -> None:
        self.quit_signal.emit()

    def report_component_failure(self, component: str) -> None:
        self.component_failure_signal.emit(component)
