import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from lock_in.rules.application_policy import FocusConfiguration
from lock_in.ui.main_window import MainWindow
from lock_in.ui.theme import apply_theme


def window(saved=None):
    application = QApplication.instance() or QApplication([])
    apply_theme(application)
    result = MainWindow(
        hide_on_close=False,
        on_save_schedule=lambda _: None,
        on_delete_schedule=lambda _: None,
        on_save_application=lambda _: None,
        on_delete_application=lambda _: None,
        on_set_capture=lambda _: None,
        on_save_settings=(saved.append if saved is not None else lambda _: None),
        on_save_website=lambda _: None,
        on_delete_website=lambda _: None,
    )
    result.update_configuration(FocusConfiguration())
    return result


def test_sidebar_navigation_keeps_operation_feedback_visible_on_each_page():
    view = window()
    view.show()
    for name in view._page_names:
        view._go(name)
        view.report_operation_error("save_schedule")
        QApplication.processEvents()
        assert view._page_title.text() == name
        assert view._status.isVisible()
        assert view._failure_banner.isVisible()
    view.close()


def test_retention_reduction_can_be_cancelled(monkeypatch):
    saved = []
    view = window(saved)
    view._retention_days.setValue(1)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No
    )
    view._save_settings()
    assert saved == []
    assert view._configuration.settings.history_retention_days == 90
    view.close()


def test_component_failure_is_visible_without_changing_pages():
    view = window()
    view._go("Settings")
    view.show()
    view.report_component_failure("database")
    QApplication.processEvents()
    assert "Local storage" in view._failure_banner.text()
    assert view._failure_banner.isVisible()
    view.close()


def test_sidebar_can_be_operated_by_keyboard_in_a_narrow_window():
    view = window()
    view.resize(760, 540)
    view.show()
    view._navigation.setFocus()
    for name in view._page_names[1:]:
        QTest.keyClick(view._navigation, Qt.Key.Key_Down)
        QApplication.processEvents()
        assert view._page_title.text() == name
        assert view._tabs.currentWidget().isVisible()
    QTest.keyClick(view._navigation, Qt.Key.Key_Home)
    assert view._page_title.text() == "Overview"
    view.close()
