"""Sidebar workspace for schedules, allowlists, local reviews and settings."""

from __future__ import annotations

import ntpath
from collections.abc import Callable
from datetime import date, datetime

from PySide6.QtCore import QDate, Qt, QTime, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
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
from lock_in.reviews.models import DailyReview
from lock_in.rules.application_policy import (
    FocusConfiguration,
    RecentApplication,
    active_schedules_at,
)
from lock_in.ui.theme import metric_card, text_label

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
        on_request_review: Callable[[date], None] = lambda _day: None,
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
        self._on_request_review = on_request_review
        self._configuration = FocusConfiguration()
        self._selected_path: str | None = None
        self._capture_active = False

        self.setWindowTitle("Lock-In")
        self.resize(1080, 780)
        self.setMinimumSize(760, 540)
        root = QWidget()
        body = QHBoxLayout(root)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 30, 18, 22)
        side.addWidget(text_label("Lock-In", "brand"))
        side.addWidget(text_label("A little space to focus.", "sidebarNote"))
        side.addSpacing(26)
        self._navigation = QListWidget()
        self._navigation.setObjectName("navigation")
        self._navigation.setAccessibleName("Main navigation")
        side.addWidget(self._navigation)
        side.addWidget(
            text_label("ON YOUR TERMS\nLocal data. Your choice.", "sidebarNote")
        )
        body.addWidget(sidebar)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(28, 26, 28, 18)
        column.setSpacing(10)
        self._page_title = text_label("Overview", "pageTitle")
        self._page_subtitle = text_label("", "subtitle")
        column.addWidget(text_label("YOUR FOCUS, INTENTIONALLY", "eyebrow"))
        column.addWidget(self._page_title)
        column.addWidget(self._page_subtitle)
        self._failure_banner = text_label("", "failureBanner")
        self._failure_banner.hide()
        column.addWidget(self._failure_banner)
        tabs = QStackedWidget()
        self._tabs = tabs
        self._status = text_label("Loading local configuration…")
        self.statusBar().addWidget(self._status, 1)
        self._review_tab = self._build_review_tab()
        pages = (
            (
                "Overview",
                "A quiet place to plan your attention.",
                self._build_overview_tab(),
            ),
            (
                "Schedules",
                "Make space for the work you want to do.",
                self._build_schedules_tab(),
            ),
            (
                "Applications",
                "Choose the tools that belong in your work time.",
                self._build_applications_tab(),
            ),
            (
                "Websites",
                "Allow useful sites. Pause before everything else.",
                self._build_websites_tab(),
            ),
            (
                "Reviews",
                "Notice your patterns, without judging them.",
                self._review_tab,
            ),
            (
                "Settings",
                "A reminder rhythm that works for you.",
                self._build_settings_tab(),
            ),
        )
        self._page_descriptions = [page[1] for page in pages]
        self._page_names = [page[0] for page in pages]
        self._page_widgets = [page[2] for page in pages]
        for name, _description, page in pages:
            self._navigation.addItem(name)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(page)
            tabs.addWidget(area)
        self._navigation.currentRowChanged.connect(self._navigate)
        column.addWidget(tabs, 1)
        body.addWidget(content, 1)
        self.setCentralWidget(root)
        self._navigation.setCurrentRow(0)
        self._overview_timer = QTimer(self)
        self._overview_timer.timeout.connect(self._refresh_overview)
        self._overview_timer.start(30_000)

    def _navigate(self, index: int) -> None:
        if index < 0:
            return
        self._tabs.setCurrentIndex(index)
        self._page_title.setText(self._page_names[index])
        self._page_subtitle.setText(self._page_descriptions[index])
        if self._page_widgets[index] is self._review_tab:
            self._request_review()

    def _go(self, name: str) -> None:
        self._navigation.setCurrentRow(self._page_names.index(name))

    def _build_overview_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(18)
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(26, 25, 26, 25)
        hero_layout.setSpacing(14)
        hero_layout.addWidget(text_label("PAUSE. CHOOSE. CONTINUE.", "eyebrow"))
        self._focus_heading = text_label("Make room for what matters.", "heroTitle")
        hero_layout.addWidget(self._focus_heading)
        self._focus_description = text_label(
            "Create a work period and choose your work tools. Lock-In will remind you to pause when you drift away."
        )
        hero_layout.addWidget(self._focus_description)
        actions = QHBoxLayout()
        create = QPushButton("Plan a work period")
        create.setProperty("variant", "primary")
        create.clicked.connect(lambda: self._go("Schedules"))
        review = QPushButton("Review today")
        review.clicked.connect(lambda: self.open_review(date.today()))
        actions.addWidget(create)
        actions.addWidget(review)
        actions.addStretch()
        hero_layout.addLayout(actions)
        layout.addWidget(hero)
        counts = QHBoxLayout()
        self._overview_metrics = []
        for title in ("Work schedules", "Allowed applications", "Allowed websites"):
            frame, value = metric_card(title, "0")
            counts.addWidget(frame, 1)
            self._overview_metrics.append(value)
        layout.addLayout(counts)
        connection = QGroupBox("Browser connection")
        connection_layout = QVBoxLayout(connection)
        self._browser_health = text_label("No browser profiles connected yet.")
        connection_layout.addWidget(self._browser_health)
        connection_layout.addWidget(
            text_label(
                "Website reminders need the Lock-In extension in each Chrome or Edge profile. If a site cannot be verified, no website prompt is shown."
            )
        )
        layout.addWidget(connection)
        layout.addWidget(
            text_label(
                "Reminders, not restrictions. You always decide whether to continue."
            )
        )
        layout.addStretch()
        return widget

    def _refresh_overview(self) -> None:
        active = active_schedules_at(
            self._configuration.schedules, datetime.now().astimezone()
        )
        if active:
            self._focus_heading.setText("You're in a work period.")
            self._focus_description.setText(
                "Active now: "
                + ", ".join(s.name for s in active)
                + ". Your work allowlists are in use."
            )
        elif self._configuration.schedules:
            self._focus_heading.setText("Ready when you are.")
            self._focus_description.setText(
                "No work period is active right now. Your saved schedules will turn reminders on automatically."
            )
        else:
            self._focus_heading.setText("Make room for what matters.")
            self._focus_description.setText(
                "Create a work period and choose your work tools. Lock-In will remind you to pause when you drift away."
            )

    def _build_schedules_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("New weekly schedule")
        form = QFormLayout(editor)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
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
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_schedule)
        form.addRow(save)
        layout.addWidget(editor)

        self._schedule_list = QListWidget()
        self._schedule_list.setMinimumHeight(140)
        layout.addWidget(QLabel("Saved schedules"))
        layout.addWidget(self._schedule_list)
        delete = QPushButton("Delete selected schedule")
        delete.setProperty("variant", "danger")
        delete.clicked.connect(self._delete_schedule)
        layout.addWidget(delete)
        return widget

    def _build_applications_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("Add allowed application")
        form = QFormLayout(editor)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._allowlist_schedule = QComboBox()
        self._allowlist_schedule.addItem("All schedules", None)
        self._capture_button = QPushButton("Select by switching to an app…")
        self._capture_button.setProperty("variant", "primary")
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
        self._application_list.setMinimumHeight(140)
        layout.addWidget(QLabel("Allowed applications"))
        layout.addWidget(self._application_list)
        delete = QPushButton("Remove selected application")
        delete.clicked.connect(self._delete_application)
        layout.addWidget(delete)
        return widget

    def _build_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("Reminders and history")
        form = QFormLayout(editor)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._follow_up_seconds = QSpinBox()
        self._follow_up_seconds.setRange(30, 86_400)
        self._follow_up_seconds.setSuffix(" seconds")
        self._follow_up_seconds.setValue(300)
        self._review_time = QTimeEdit(QTime(20, 0))
        self._review_time.setDisplayFormat("HH:mm")
        self._retention_days = QSpinBox()
        self._retention_days.setRange(1, 3650)
        self._retention_days.setValue(90)
        self._retention_days.setSuffix(" days")
        save = QPushButton("Save settings")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_settings)
        form.addRow("Remind again after", self._follow_up_seconds)
        form.addRow("Daily review (local time)", self._review_time)
        form.addRow("Keep history for", self._retention_days)
        form.addRow(save)
        layout.addWidget(editor)
        explanation = QLabel(
            "The interval counts only while a program you chose to continue "
            "using remains in the foreground. Lock, sleep, and other windows "
            "are excluded."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        note = QLabel(
            "Daily reviews are sent while Lock-In is running, with one latest "
            "missed review after restart or wake. Windows may hide notifications. "
            "Older history is permanently removed at the selected retention limit. "
            "Schedules and allowlists are preserved."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return widget

    def _build_review_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self._review_date = QDateEdit(QDate.currentDate())
        self._review_date.setCalendarPopup(True)
        self._review_date.setDisplayFormat("yyyy-MM-dd")
        self._review_date.dateChanged.connect(lambda _date: self._request_review())
        refresh = QPushButton("Refresh review")
        refresh.clicked.connect(self._request_review)
        controls.addWidget(self._review_date)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        metrics = QHBoxLayout()
        self._review_metrics = []
        for title in (
            "Recorded time",
            "Outside allowlist",
            "Entry prompts",
            "Follow-ups",
        ):
            card, value = metric_card(title, "—")
            metrics.addWidget(card, 1)
            self._review_metrics.append(value)
        layout.addLayout(metrics)
        self._review_summary = QLabel("Loading review…")
        self._review_summary.setWordWrap(True)
        layout.addWidget(self._review_summary)
        note = QLabel(
            "Recorded time covers active schedules while Lock-In is running and "
            "Windows is available. Overlapping schedules count once. Unknown sites "
            "and Lock-In windows are not counted as outside the allowlist. "
            "Dates use the local time recorded at each event; pre-M6 history has "
            "no reliable local-day or duration data. Today is a partial review."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self._review_details = QListWidget()
        self._review_details.setMinimumHeight(180)
        layout.addWidget(self._review_details)
        return widget

    def _request_review(self) -> None:
        self._review_summary.setText("Loading review…")
        self._review_details.clear()
        for label in self._review_metrics:
            label.setText("—")
        self._on_request_review(self._review_date.date().toPython())

    def open_review(self, day: date) -> None:
        self._review_date.setDate(QDate(day.year, day.month, day.day))
        self._go("Reviews")
        self._request_review()

    def update_review(self, review: DailyReview) -> None:
        if review.day != self._review_date.date().toPython():
            return
        values = (
            f"{review.scheduled_ms / 60000:.1f} min",
            f"{review.outside_ms / 60000:.1f} min",
            str(review.entries),
            str(review.follow_ups),
        )
        for label, value in zip(self._review_metrics, values, strict=True):
            label.setText(value)
        self._review_summary.setText(
            f"Continue: {review.continues} · Return: {review.returns}\n"
            f"Notification: {review.delivery_status}\n"
            f"Showing {len(review.details)} of {review.event_count} events (newest first)."
        )
        self._review_summary.setToolTip(
            f"Recorded: {review.scheduled_ms / 1000:.0f} seconds; outside allowlist: {review.outside_ms / 1000:.0f} seconds"
        )
        self._review_details.clear()
        for event in review.details:
            target = (
                ntpath.basename(event.target_key)
                if event.target_type == "application"
                else event.target_key
            )
            self._review_details.addItem(
                f"{event.occurred_at} · {event.target_type}: {target} · "
                f"{event.decision.replace('_', ' ')} ({event.prompt_kind.replace('_', ' ')})"
            )

    def _build_websites_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        editor = QGroupBox("Add allowed website")
        form = QFormLayout(editor)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._website_domain = QLineEdit()
        self._website_domain.setPlaceholderText("example.com")
        self._website_schedule = QComboBox()
        self._website_schedule.addItem("All schedules", None)
        self._website_subdomains = QCheckBox("Include subdomains")
        self._website_subdomains.setChecked(True)
        save = QPushButton("Add website")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_website)
        form.addRow("Domain", self._website_domain)
        form.addRow("Applies to", self._website_schedule)
        form.addRow(self._website_subdomains)
        form.addRow(save)
        layout.addWidget(editor)
        self._website_list = QListWidget()
        self._website_list.setMinimumHeight(140)
        layout.addWidget(QLabel("Allowed websites"))
        layout.addWidget(self._website_list)
        remove = QPushButton("Remove selected website")
        remove.clicked.connect(self._delete_website)
        layout.addWidget(remove)
        return widget

    def update_configuration(self, configuration: FocusConfiguration) -> None:
        self._configuration = configuration
        self._follow_up_seconds.setValue(configuration.settings.follow_up_seconds)
        self._review_time.setTime(
            QTime(
                configuration.settings.review_time.hour,
                configuration.settings.review_time.minute,
            )
        )
        self._retention_days.setValue(configuration.settings.history_retention_days)
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
        for label, value in zip(
            self._overview_metrics,
            (
                len(configuration.schedules),
                len(configuration.applications),
                len(configuration.websites),
            ),
            strict=True,
        ):
            label.setText(str(value))
        self._refresh_overview()

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
        self._failure_banner.setText(
            "That change could not be completed. Your saved data has not been reset. Try again, or restart Lock-In if this continues."
        )
        self._failure_banner.show()
        if operation.startswith("review_"):
            self._review_summary.setText(
                "Review data could not be loaded or saved. Please refresh; check Overview for component status."
            )

    def report_browser_health(self, message: str) -> None:
        self._browser_health.setText(message)

    def report_component_failure(self, component: str) -> None:
        names = {
            "database": "Local storage",
            "configuration": "Saved settings",
            "foreground_monitor": "Application monitoring",
            "browser_ipc": "Browser connection",
            "focus_service": "Focus reminders",
            "reviews": "Daily reviews",
        }
        self._failure_banner.setText(
            f"{names.get(component, 'A background service')} needs attention. Lock-In will not block your work. Exit and restart; do not delete your data to recover."
        )
        self._failure_banner.show()
        self._status.setText(
            "Limited functionality — a service did not start correctly."
        )

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
        if (
            self._retention_days.value()
            < self._configuration.settings.history_retention_days
        ):
            answer = QMessageBox.question(
                self,
                "Shorten history retention?",
                "Older activity records will be permanently removed at the next cleanup. Schedules and allowlists will remain. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._on_save_settings(
            AppSettings(
                review_time=self._review_time.time().toPython(),
                history_retention_days=self._retention_days.value(),
                follow_up_seconds=self._follow_up_seconds.value(),
            )
        )
        self._status.setText("Saving settings…")

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
