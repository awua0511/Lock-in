import os
from datetime import date, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication, QMessageBox

from lock_in.domain.models import AppSettings
from lock_in.reviews.models import DailyReview
from lock_in.rules.application_policy import FocusConfiguration
from lock_in.ui.main_window import MainWindow
from lock_in.ui.shell import DesktopShell


def test_review_settings_round_trip_and_selected_day_content(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes
    )
    _ = QApplication.instance() or QApplication([])
    settings = []
    requested = []
    window = MainWindow(
        hide_on_close=False,
        on_save_schedule=lambda _x: None,
        on_delete_schedule=lambda _x: None,
        on_save_application=lambda _x: None,
        on_delete_application=lambda _x: None,
        on_set_capture=lambda _x: None,
        on_save_settings=settings.append,
        on_save_website=lambda _x: None,
        on_delete_website=lambda _x: None,
        on_request_review=requested.append,
    )
    window.update_configuration(
        FocusConfiguration(settings=AppSettings(time(21), 30, 60))
    )
    window._review_time.setTime(QTime(22, 15))
    window._retention_days.setValue(7)
    window._save_settings()
    assert settings == [AppSettings(time(22, 15), 7, 60)]
    day = date(2026, 9, 28)
    window.open_review(day)
    assert requested[-1] == day
    window.update_review(DailyReview(day, 60000, 30000, 1, 1, 2, 0, 0, ()))
    assert window._review_metrics[0].text() == "1.0 min"
    assert "60 seconds" in window._review_summary.toolTip()
    assert "Continue: 2" in window._review_summary.text()
    window.close()


def test_notification_without_tray_records_unavailable():
    shell = DesktopShell.__new__(DesktopShell)
    shell._tray = None
    results = []
    shell._on_notification_result = results.append
    review = DailyReview(date(2026, 9, 28), 0, 0, 0, 0, 0, 0, 0, ())
    shell.show_review_notification(review)
    assert results[0].status == "unavailable"


def test_notification_submission_is_not_claimed_as_visible():
    class Tray:
        def isVisible(self):
            return True

        def supportsMessages(self):
            return True

        def showMessage(self, title, message, icon, timeout):
            self.message = (title, message)

    shell = DesktopShell.__new__(DesktopShell)
    shell._tray = Tray()
    results = []
    shell._on_notification_result = results.append
    review = DailyReview(date(2026, 9, 28), 0, 0, 0, 0, 0, 0, 0, ())
    shell.show_review_notification(review)
    assert results[0].status == "submitted_to_windows"
    assert "2026-09-28" in shell._tray.message[0]
