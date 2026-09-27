"""Milestone 3 schedule and application-allowlist settings window."""

from __future__ import annotations

import ntpath
from collections.abc import Callable
from datetime import date

from PySide6.QtCore import Qt, QTime
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
    AppSettings,
    Recurrence,
    RecurrenceKind,
    Schedule,
    WebsiteAllowlistEntry,
)
from lock_in.rules.application_policy import FocusConfiguration, RecentApplication

ScheduleCallback = Callable[[Schedule], None]
IdentifierCallback = Callable[[str], None]
ApplicationCallback = Callable[[ApplicationAllowlistEntry], None]
CaptureCallback = Callable[[bool], None]
SettingsCallback = Callable[[AppSettings], None]
WebsiteCallback = Callable[[WebsiteAllowlistEntry], None]


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        hide_on_close: bool,
        on_save_schedule: ScheduleCallback,
        on_delete_schedule: IdentifierCallback,
        on_save_application: ApplicationCallback,
        on_delete_application: IdentifierCallback,
        on_set_capture: CaptureCallback,
        on_save_settings: SettingsCallback,
        on_save_website: WebsiteCallback,
        on_delete_website: IdentifierCallback,
    ) -> None:
        super().__init__()
        self._hide_on_close = hide_on_close
        self._on_save_schedule = on_save_schedule
        self._on_delete_schedule = on_delete_schedule
        self._on_save_application = on_save_application
        self._on_delete_application = on_delete_application
        self._on_set_capture = on_set_capture
        self._on_save_settings = on_save_settings
        self._on_save_website = on_save_website
        self._on_delete_website = on_delete_website
        self._configuration = FocusConfiguration()
        self._selected_path: str | None = None
        self._capture_active = False

        self.setWindowTitle("Lock-In")
        self.resize(720, 560)
        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_schedules_tab(), "Schedules")
        tabs.addTab(self._build_applications_tab(), "Applications")
        tabs.addTab(self._build_settings_tab(), "Settings")
        tabs.addTab(self._build_websites_tab(), "Websites")
        self.setCentralWidget(tabs)

    def _build_overview_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel("Lock-In application focus loop")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        description = QLabel(
            "Create a weekly work schedule, then add applications that are "
            "appropriate during that schedule. Entering another application "
            "will show a decision prompt."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self._status = QLabel("Loading local configuration…")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._browser_health = QLabel("Browser extension status — Chrome: 0; Edge: 0")
        self._browser_health.setWordWrap(True)
        layout.addWidget(self._browser_health)
        layout.addStretch()
        return widget

    def _build_schedules_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("New weekly schedule")
        form = QFormLayout(editor)
        self._schedule_name = QLineEdit("Focus session")
        self._schedule_start = QTimeEdit(QTime(13, 0))
        self._schedule_end = QTimeEdit(QTime(13, 40))
        self._schedule_start.setDisplayFormat("HH:mm")
        self._schedule_end.setDisplayFormat("HH:mm")
        form.addRow("Name", self._schedule_name)
        form.addRow("Start", self._schedule_start)
        form.addRow("End", self._schedule_end)

        day_widget = QWidget()
        day_layout = QHBoxLayout(day_widget)
        day_layout.setContentsMargins(0, 0, 0, 0)
        self._day_checks: list[QCheckBox] = []
        for index, label in enumerate(
            ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        ):
            checkbox = QCheckBox(label)
            checkbox.setChecked(index == date.today().weekday())
            self._day_checks.append(checkbox)
            day_layout.addWidget(checkbox)
        form.addRow("Days", day_widget)
        save = QPushButton("Create schedule")
        save.clicked.connect(self._save_schedule)
        form.addRow(save)
        layout.addWidget(editor)

        self._schedule_list = QListWidget()
        layout.addWidget(QLabel("Saved schedules"))
        layout.addWidget(self._schedule_list)
        delete = QPushButton("Delete selected schedule")
        delete.clicked.connect(self._delete_schedule)
        layout.addWidget(delete)
        return widget

    def _build_applications_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("Add allowed application")
        form = QFormLayout(editor)
        self._allowlist_schedule = QComboBox()
        self._allowlist_schedule.addItem("All schedules", None)
        self._capture_button = QPushButton("Select by switching to an app…")
        self._capture_button.clicked.connect(self._toggle_capture)
        self._recent_combo = QComboBox()
        self._recent_combo.currentIndexChanged.connect(self._select_recent)
        self._path_label = QLabel("No application selected")
        self._path_label.setWordWrap(True)
        browse = QPushButton("Browse for .exe…")
        browse.clicked.connect(self._browse_application)
        add = QPushButton("Add to allowlist")
        add.clicked.connect(self._save_application)
        form.addRow("Applies to", self._allowlist_schedule)
        form.addRow("Quick select", self._capture_button)
        form.addRow("Recently observed", self._recent_combo)
        form.addRow("Executable", self._path_label)
        form.addRow(browse)
        form.addRow(add)
        layout.addWidget(editor)

        self._application_list = QListWidget()
        layout.addWidget(QLabel("Allowed applications"))
        layout.addWidget(self._application_list)
        delete = QPushButton("Remove selected application")
        delete.clicked.connect(self._delete_application)
        layout.addWidget(delete)
        return widget

    def _build_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("Follow-up reminder")
        form = QFormLayout(editor)
        self._follow_up_seconds = QSpinBox()
        self._follow_up_seconds.setRange(30, 86_400)
        self._follow_up_seconds.setSuffix(" seconds")
        self._follow_up_seconds.setValue(300)
        save = QPushButton("Save reminder interval")
        save.clicked.connect(self._save_settings)
        form.addRow("Remind again after", self._follow_up_seconds)
        form.addRow(save)
        layout.addWidget(editor)
        explanation = QLabel(
            "The interval counts only while a program you chose to continue "
            "using remains in the foreground. Lock, sleep, and other windows "
            "are excluded."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        layout.addStretch()
        return widget

    def _build_websites_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("Add allowed website")
        form = QFormLayout(editor)
        self._website_domain = QLineEdit()
        self._website_domain.setPlaceholderText("example.com")
        self._website_schedule = QComboBox()
        self._website_schedule.addItem("All schedules", None)
        self._website_subdomains = QCheckBox("Include subdomains")
        self._website_subdomains.setChecked(True)
        save = QPushButton("Add website")
        save.clicked.connect(self._save_website)
        form.addRow("Domain", self._website_domain)
        form.addRow("Applies to", self._website_schedule)
        form.addRow(self._website_subdomains)
        form.addRow(save)
        layout.addWidget(editor)
        self._website_list = QListWidget()
        layout.addWidget(QLabel("Allowed websites"))
        layout.addWidget(self._website_list)
        remove = QPushButton("Remove selected website")
        remove.clicked.connect(self._delete_website)
        layout.addWidget(remove)
        return widget

    def update_configuration(self, configuration: FocusConfiguration) -> None:
        self._configuration = configuration
        self._follow_up_seconds.setValue(configuration.settings.follow_up_seconds)
        self._schedule_list.clear()
        day_names = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        for schedule in configuration.schedules:
            days = ", ".join(
                day_names[recurrence.weekday]
                for recurrence in schedule.recurrences
                if recurrence.weekday is not None
            )
            item = QListWidgetItem(
                f"{schedule.name}: {schedule.start_time:%H:%M}–"
                f"{schedule.end_time:%H:%M} ({days})"
            )
            item.setData(Qt.ItemDataRole.UserRole, schedule.id)
            self._schedule_list.addItem(item)

        selected_schedule = self._allowlist_schedule.currentData()
        self._allowlist_schedule.clear()
        self._allowlist_schedule.addItem("All schedules", None)
        schedule_names = {
            schedule.id: schedule.name for schedule in configuration.schedules
        }
        for schedule in configuration.schedules:
            self._allowlist_schedule.addItem(schedule.name, schedule.id)
        index = self._allowlist_schedule.findData(selected_schedule)
        if index >= 0:
            self._allowlist_schedule.setCurrentIndex(index)
        elif configuration.schedules:
            self._allowlist_schedule.setCurrentIndex(1)

        website_schedule = self._website_schedule.currentData()
        self._website_schedule.clear()
        self._website_schedule.addItem("All schedules", None)
        for schedule in configuration.schedules:
            self._website_schedule.addItem(schedule.name, schedule.id)
        website_index = self._website_schedule.findData(website_schedule)
        if website_index >= 0:
            self._website_schedule.setCurrentIndex(website_index)
        elif configuration.schedules:
            self._website_schedule.setCurrentIndex(1)

        self._application_list.clear()
        for entry in configuration.applications:
            scope = schedule_names.get(entry.schedule_id, "All schedules")
            item = QListWidgetItem(f"{entry.identity.display_name} — {scope}")
            item.setToolTip(entry.identity.executable_path or "")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self._application_list.addItem(item)
        self._website_list.clear()
        for entry in configuration.websites:
            scope = schedule_names.get(entry.schedule_id, "All schedules")
            subdomains = "+ subdomains" if entry.include_subdomains else "exact host"
            item = QListWidgetItem(f"{entry.domain} — {scope} — {subdomains}")
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self._website_list.addItem(item)
        self._status.setText(
            f"Loaded {len(configuration.schedules)} schedule(s) and "
            f"{len(configuration.applications)} allowed application(s)."
        )

    def update_recent_applications(
        self, applications: tuple[RecentApplication, ...]
    ) -> None:
        selected = self._selected_path
        self._recent_combo.blockSignals(True)
        self._recent_combo.clear()
        self._recent_combo.addItem("Choose a recently observed application…", None)
        for application in applications:
            self._recent_combo.addItem(
                application.display_name,
                application.executable_path,
            )
        self._recent_combo.blockSignals(False)
        if selected:
            index = self._recent_combo.findData(selected)
            if index >= 0:
                self._recent_combo.setCurrentIndex(index)

    def report_operation_error(self, operation: str) -> None:
        self._status.setText(f"The operation failed safely: {operation}.")

    def report_browser_health(self, message: str) -> None:
        self._browser_health.setText(message)

    def application_captured(self, application: RecentApplication) -> None:
        self._capture_active = False
        self._capture_button.setText("Select by switching to an app…")
        self._selected_path = application.executable_path
        self._path_label.setText(application.executable_path)
        index = self._recent_combo.findData(application.executable_path)
        if index >= 0:
            self._recent_combo.setCurrentIndex(index)
        self._status.setText(
            f"Selected {application.display_name}. Review the scope, then click "
            "Add to allowlist."
        )
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._hide_on_close:
            self.hide()
            event.ignore()
            return
        event.accept()

    def _save_schedule(self) -> None:
        name = self._schedule_name.text().strip()
        weekdays = [
            index
            for index, checkbox in enumerate(self._day_checks)
            if checkbox.isChecked()
        ]
        if not name or not weekdays:
            self._status.setText("A schedule needs a name and at least one day.")
            return
        start = self._schedule_start.time().toPython()
        end = self._schedule_end.time().toPython()
        if start == end:
            self._status.setText("Start and end times must differ.")
            return
        schedule = Schedule(
            name=name,
            start_time=start,
            end_time=end,
            timezone="local",
            recurrences=tuple(
                Recurrence(kind=RecurrenceKind.WEEKLY, weekday=weekday)
                for weekday in weekdays
            ),
        )
        self._on_save_schedule(schedule)
        self._status.setText("Saving schedule…")

    def _delete_schedule(self) -> None:
        item = self._schedule_list.currentItem()
        if item is None:
            self._status.setText("Select a schedule to delete.")
            return
        response = QMessageBox.question(
            self,
            "Delete schedule",
            "Delete this schedule and its scoped allowlist entries?",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self._on_delete_schedule(item.data(Qt.ItemDataRole.UserRole))
        self._status.setText("Deleting schedule…")

    def _select_recent(self, index: int) -> None:
        path = self._recent_combo.itemData(index)
        if path:
            self._selected_path = path
            self._path_label.setText(path)

    def _toggle_capture(self) -> None:
        self._capture_active = not self._capture_active
        self._on_set_capture(self._capture_active)
        if self._capture_active:
            self._capture_button.setText("Cancel switching selection")
            self._status.setText(
                "Switch to the application you want to allow. Lock-In will "
                "select it and return here."
            )
        else:
            self._capture_button.setText("Select by switching to an app…")
            self._status.setText("Application selection cancelled.")

    def _browse_application(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose an application",
            "",
            "Applications (*.exe)",
        )
        if path:
            self._selected_path = path
            self._path_label.setText(path)

    def _save_application(self) -> None:
        path = self._selected_path
        if not path:
            self._status.setText(
                "Select an application by switching to it, choose a recent app, "
                "or browse for an .exe."
            )
            return
        name = ntpath.splitext(ntpath.basename(path))[0] or ntpath.basename(path)
        entry = ApplicationAllowlistEntry(
            schedule_id=self._allowlist_schedule.currentData(),
            identity=ApplicationIdentity(
                kind=ApplicationKind.WIN32,
                display_name=name,
                executable_path=path,
            ),
        )
        self._on_save_application(entry)
        self._status.setText("Saving allowed application…")

    def _delete_application(self) -> None:
        item = self._application_list.currentItem()
        if item is None:
            self._status.setText("Select an application to remove.")
            return
        self._on_delete_application(item.data(Qt.ItemDataRole.UserRole))
        self._status.setText("Removing allowed application…")

    def _save_settings(self) -> None:
        current = self._configuration.settings
        self._on_save_settings(
            AppSettings(
                review_time=current.review_time,
                history_retention_days=current.history_retention_days,
                follow_up_seconds=self._follow_up_seconds.value(),
            )
        )
        self._status.setText("Saving reminder interval…")

    def _save_website(self) -> None:
        try:
            entry = WebsiteAllowlistEntry(
                domain=self._website_domain.text(),
                schedule_id=self._website_schedule.currentData(),
                include_subdomains=self._website_subdomains.isChecked(),
            )
        except ValueError:
            self._status.setText("Enter a hostname such as example.com, not a URL.")
            return
        self._on_save_website(entry)
        self._website_domain.clear()
        self._status.setText("Saving website allowlist entry…")

    def _delete_website(self) -> None:
        item = self._website_list.currentItem()
        if item is None:
            self._status.setText("Select a website to remove.")
            return
        self._on_delete_website(item.data(Qt.ItemDataRole.UserRole))
        self._status.setText("Removing website allowlist entry…")
