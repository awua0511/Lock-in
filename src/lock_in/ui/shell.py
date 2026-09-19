"""Main window and system tray ownership on the Qt UI thread."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from lock_in.ui.bridge import QtUiBridge
from lock_in.ui.main_window import MainWindow


class DesktopShell:
    def __init__(
        self,
        application: QApplication,
        bridge: QtUiBridge,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
        *,
        tray_enabled: bool = True,
    ) -> None:
        self._application = application
        self._tray: QSystemTrayIcon | None = None
        self.last_failed_component: str | None = None

        tray_available = tray_enabled and QSystemTrayIcon.isSystemTrayAvailable()
        self._window = MainWindow(hide_on_close=tray_available)
        application.setQuitOnLastWindowClosed(not tray_available)

        bridge.show_main_window_signal.connect(self.show_main_window)
        bridge.quit_signal.connect(application.quit)
        bridge.component_failure_signal.connect(self.report_component_failure)

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
        if self._tray is not None:
            self._tray.hide()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason is QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()
