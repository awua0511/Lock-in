"""Main window and system tray ownership on the Qt UI thread."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from lock_in.domain.models import ApplicationAllowlistEntry, Schedule
from lock_in.rules.application_policy import (
    AttentionPrompt,
    FocusConfiguration,
    PolicyDecision,
    RecentApplication,
)
from lock_in.ui.bridge import QtUiBridge
from lock_in.ui.main_window import MainWindow
from lock_in.ui.prompt_dialog import AttentionPromptDialog


class DesktopShell:
    def __init__(
        self,
        application: QApplication,
        bridge: QtUiBridge,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
        on_save_schedule: Callable[[Schedule], None],
        on_delete_schedule: Callable[[str], None],
        on_save_application: Callable[[ApplicationAllowlistEntry], None],
        on_delete_application: Callable[[str], None],
        on_set_application_capture: Callable[[bool], None],
        on_prompt_decision: Callable[[str, PolicyDecision], None],
        *,
        tray_enabled: bool = True,
    ) -> None:
        self._application = application
        self._tray: QSystemTrayIcon | None = None
        self.last_failed_component: str | None = None
        self._prompt: AttentionPromptDialog | None = None
        self._on_prompt_decision = on_prompt_decision

        tray_available = tray_enabled and QSystemTrayIcon.isSystemTrayAvailable()
        self._window = MainWindow(
            hide_on_close=tray_available,
            on_save_schedule=on_save_schedule,
            on_delete_schedule=on_delete_schedule,
            on_save_application=on_save_application,
            on_delete_application=on_delete_application,
            on_set_capture=on_set_application_capture,
        )
        application.setQuitOnLastWindowClosed(not tray_available)

        bridge.show_main_window_signal.connect(self.show_main_window)
        bridge.quit_signal.connect(application.quit)
        bridge.component_failure_signal.connect(self.report_component_failure)
        bridge.configuration_signal.connect(self.update_configuration)
        bridge.recent_applications_signal.connect(self.update_recent_applications)
        bridge.application_captured_signal.connect(self.application_captured)
        bridge.show_attention_prompt_signal.connect(self.show_attention_prompt)
        bridge.dismiss_attention_prompt_signal.connect(self.dismiss_attention_prompt)
        bridge.operation_error_signal.connect(self._window.report_operation_error)

        if tray_available:
            menu = QMenu()
            open_action = QAction("Open", menu)
            open_action.triggered.connect(on_open)
            menu.addAction(open_action)
            menu.addSeparator()
            exit_action = QAction("Exit", menu)
            exit_action.triggered.connect(on_exit)
            menu.addAction(exit_action)

            icon = application.style().standardIcon(
                QStyle.StandardPixmap.SP_DialogApplyButton
            )
            application.setWindowIcon(icon)
            self._tray = QSystemTrayIcon(icon, application)
            self._tray.setToolTip("Lock-In")
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(self._on_tray_activated)
            self._tray.show()

    @property
    def tray_visible(self) -> bool:
        return self._tray is not None and self._tray.isVisible()

    def show_main_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def report_component_failure(self, component: str) -> None:
        self.last_failed_component = component
        if self._tray is not None:
            self._tray.setToolTip("Lock-In (a component needs attention)")

    def close(self) -> None:
        self.dismiss_attention_prompt()
        if self._tray is not None:
            self._tray.hide()

    def update_configuration(self, configuration: FocusConfiguration) -> None:
        self._window.update_configuration(configuration)

    def update_recent_applications(
        self, applications: tuple[RecentApplication, ...]
    ) -> None:
        self._window.update_recent_applications(applications)

    def application_captured(self, application: RecentApplication) -> None:
        self._window.application_captured(application)

    def show_attention_prompt(self, prompt: AttentionPrompt) -> None:
        self.dismiss_attention_prompt()
        self._prompt = AttentionPromptDialog(prompt, self._on_prompt_decision)
        self._prompt.show()
        self._prompt.raise_()
        self._prompt.activateWindow()

    def dismiss_attention_prompt(self) -> None:
        if self._prompt is None:
            return
        prompt = self._prompt
        self._prompt = None
        prompt.dismiss_stale()
        prompt.deleteLater()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()
