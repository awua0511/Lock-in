"""Qt signal bridge safe to call from the application event thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class QtUiBridge(QObject):
    show_main_window_signal = Signal()
    quit_signal = Signal()
    component_failure_signal = Signal(str)
    configuration_signal = Signal(object)
    recent_applications_signal = Signal(object)
    application_captured_signal = Signal(object)
    show_attention_prompt_signal = Signal(object)
    dismiss_attention_prompt_signal = Signal()
    operation_error_signal = Signal(str)

    def show_main_window(self) -> None:
        self.show_main_window_signal.emit()

    def request_quit(self) -> None:
        self.quit_signal.emit()

    def report_component_failure(self, component: str) -> None:
        self.component_failure_signal.emit(component)

    def update_focus_configuration(self, configuration: object) -> None:
        self.configuration_signal.emit(configuration)

    def update_recent_applications(self, applications: object) -> None:
        self.recent_applications_signal.emit(applications)

    def application_captured(self, application: object) -> None:
        self.application_captured_signal.emit(application)

    def show_attention_prompt(self, prompt: object) -> None:
        self.show_attention_prompt_signal.emit(prompt)

    def dismiss_attention_prompt(self) -> None:
        self.dismiss_attention_prompt_signal.emit()

    def report_operation_error(self, operation: str) -> None:
        self.operation_error_signal.emit(operation)
