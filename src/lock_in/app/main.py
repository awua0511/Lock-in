"""Production Lock-In desktop application entry point."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from lock_in.app.config import (
    APPLICATION_NAME,
    APPLICATION_VERSION,
    ORGANIZATION_NAME,
    SHUTDOWN_TIMEOUT_SECONDS,
    application_data_directory,
    clear_user_requested_exit,
    log_directory,
    mark_user_requested_exit,
    user_requested_exit,
)
from lock_in.app.configuration_service import ConfigurationService
from lock_in.app.coordinator import ApplicationCoordinator
from lock_in.app.event_bus import SerializedEventBus
from lock_in.app.events import (
    ApplicationEvent,
    ApplicationEventKind,
    BrowserIpcEvent,
    PromptDecisionEvent,
    SystemAvailabilityEvent,
    TimingTickEvent,
)
from lock_in.app.focus_service import FocusApplicationService
from lock_in.app.lifecycle import ApplicationLifecycle
from lock_in.app.logging_setup import configure_application_logging, safe_log
from lock_in.app.review_service import ReviewService
from lock_in.context.application_service import BrowserContextApplicationService
from lock_in.ipc.pipe_server import BrowserPipeServer
from lock_in.monitoring.foreground_service import ForegroundMonitoringService
from lock_in.platform.windows.local_identity import (
    SingleInstanceMutex,
    application_mutex_name,
    application_pipe_address,
)
from lock_in.platform.windows.window_activation import WindowActivator
from lock_in.rules.application_policy import ApplicationFocusPolicy
from lock_in.storage.database import database_path
from lock_in.storage.repositories import Repositories
from lock_in.storage.reviews import ReviewRepository
from lock_in.storage.worker import DatabaseWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Lock-In desktop application.")
    parser.add_argument(
        "--instance-namespace", default="default", help=argparse.SUPPRESS
    )
    parser.add_argument("--log-directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--data-directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--no-tray", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host-launched", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diagnostics-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "--smoke-test-duration", type=float, metavar="SECONDS", help=argparse.SUPPRESS
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.name != "nt":
        print("Lock-In currently requires Windows.", file=sys.stderr)
        return 2
    if args.smoke_test_duration is not None and args.smoke_test_duration <= 0:
        print("--smoke-test-duration must be greater than zero.", file=sys.stderr)
        return 2

    logger = configure_application_logging(args.log_directory or log_directory())
    mutex = SingleInstanceMutex(application_mutex_name(args.instance_namespace))
    if mutex.already_exists:
        safe_log(
            logger,
            logging.INFO,
            "duplicate_start_rejected",
            pid=os.getpid(),
        )
        mutex.close()
        return 0

    try:
        if args.host_launched and user_requested_exit():
            return 0
        if (
            not args.host_launched
            and args.instance_namespace == "default"
            and args.data_directory is None
        ):
            clear_user_requested_exit()
        return _run_application(args, logger)
    finally:
        mutex.close()


def _run_application(args: argparse.Namespace, logger: logging.Logger) -> int:
    startup_started = time.monotonic()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from lock_in.ui.bridge import QtUiBridge
    from lock_in.ui.shell import DesktopShell
    from lock_in.ui.theme import apply_theme

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName(APPLICATION_NAME)
    application.setApplicationVersion(APPLICATION_VERSION)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setQuitOnLastWindowClosed(False)
    apply_theme(application)

    bridge = QtUiBridge()
    database_worker = DatabaseWorker(
        database_path(args.data_directory or application_data_directory())
    )
    repositories = Repositories.create(database_worker)
    reviews = ReviewService(
        ReviewRepository(database_worker),
        bridge,
        logger,
        lambda event: event_bus.publish(event),
    )
    focus_service = FocusApplicationService(
        ApplicationFocusPolicy(),
        repositories.history,
        bridge,
        WindowActivator(),
        logger,
        reviews=reviews,
    )
    configuration_service = ConfigurationService(
        repositories,
        focus_service,
        bridge,
        logger,
        lambda configuration: event_bus.publish(
            ApplicationEvent(
                kind=ApplicationEventKind.CONFIGURATION_LOADED,
                source="configuration",
                payload=configuration,
            )
        ),
    )
    pipe_server = BrowserPipeServer(
        application_pipe_address(args.instance_namespace),
        lambda browser_event: event_bus.publish(
            ApplicationEvent(
                kind=ApplicationEventKind.BROWSER_IPC_EVENT,
                source="browser_ipc",
                payload=BrowserIpcEvent(
                    browser_event, time.monotonic_ns() // 1_000_000
                ),
            )
        ),
        logger,
    )
    browser_context = BrowserContextApplicationService(
        focus_service, pipe_server.send, bridge.report_browser_health
    )
    coordinator = ApplicationCoordinator(
        bridge,
        logger,
        configuration=configuration_service,
        focus=focus_service,
        browser_context=browser_context,
        on_explicit_exit=(
            mark_user_requested_exit
            if args.instance_namespace == "default" and args.data_directory is None
            else None
        ),
        reviews=reviews,
    )
    event_bus = SerializedEventBus(
        coordinator.handle, logger, measure=args.diagnostics_file is not None
    )
    monitor = ForegroundMonitoringService(
        lambda observation: event_bus.publish(
            ApplicationEvent(
                kind=ApplicationEventKind.FOREGROUND_OBSERVED,
                source="foreground_monitor",
                payload=observation,
            )
        )
    )
    lifecycle = ApplicationLifecycle(
        (
            database_worker,
            focus_service,
            reviews,
            configuration_service,
            monitor,
            pipe_server,
        ),
        event_bus,
        logger,
    )

    def publish(
        kind: ApplicationEventKind,
        source: str,
        payload: object | None = None,
    ) -> None:
        event_bus.publish(ApplicationEvent(kind=kind, source=source, payload=payload))

    shell = DesktopShell(
        application,
        bridge,
        lambda: publish(ApplicationEventKind.SHOW_MAIN_WINDOW, "tray"),
        lambda: publish(ApplicationEventKind.SHUTDOWN_REQUESTED, "tray"),
        lambda schedule: publish(
            ApplicationEventKind.SAVE_SCHEDULE, "settings", schedule
        ),
        lambda schedule_id: publish(
            ApplicationEventKind.DELETE_SCHEDULE, "settings", schedule_id
        ),
        lambda entry: publish(
            ApplicationEventKind.SAVE_APPLICATION_ALLOWLIST, "settings", entry
        ),
        lambda entry_id: publish(
            ApplicationEventKind.DELETE_APPLICATION_ALLOWLIST, "settings", entry_id
        ),
        lambda enabled: publish(
            ApplicationEventKind.SET_APPLICATION_CAPTURE, "settings", enabled
        ),
        lambda settings: publish(
            ApplicationEventKind.SAVE_SETTINGS, "settings", settings
        ),
        lambda available, reason, monotonic_ms: publish(
            ApplicationEventKind.SYSTEM_AVAILABILITY_CHANGED,
            "windows_system_events",
            SystemAvailabilityEvent(available, monotonic_ms, reason),
        ),
        lambda entry: publish(
            ApplicationEventKind.SAVE_WEBSITE_ALLOWLIST, "settings", entry
        ),
        lambda entry_id: publish(
            ApplicationEventKind.DELETE_WEBSITE_ALLOWLIST, "settings", entry_id
        ),
        lambda prompt_id, decision: publish(
            ApplicationEventKind.PROMPT_DECIDED,
            "prompt",
            PromptDecisionEvent(prompt_id, decision.value),
        ),
        tray_enabled=not args.no_tray,
        on_request_review=lambda day: publish(
            ApplicationEventKind.REQUEST_REVIEW, "reviews_ui", day
        ),
        on_notification_result=lambda result: publish(
            ApplicationEventKind.REVIEW_NOTIFICATION_RESULT, "notification", result
        ),
    )
    shutdown_lock = threading.Lock()
    shutdown_complete = False

    def shutdown() -> None:
        nonlocal shutdown_complete
        with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_complete = True
        event_bus.stop(SHUTDOWN_TIMEOUT_SECONDS)
        lifecycle.stop(SHUTDOWN_TIMEOUT_SECONDS)
        shell.close()
        if args.diagnostics_file is not None:
            args.diagnostics_file.parent.mkdir(parents=True, exist_ok=True)
            args.diagnostics_file.write_text(
                json.dumps(
                    {"startup_ms": startup_ms, **event_bus.measurements()}, indent=2
                ),
                encoding="utf-8",
            )
        safe_log(logger, logging.INFO, "application_stopped", pid=os.getpid())

    application.aboutToQuit.connect(shutdown)
    event_bus.start()
    lifecycle.start()
    event_bus.publish(
        ApplicationEvent(kind=ApplicationEventKind.STARTED, source="application")
    )
    event_bus.publish(
        ApplicationEvent(
            kind=ApplicationEventKind.SHOW_MAIN_WINDOW,
            source="application_startup",
        )
    )
    safe_log(logger, logging.INFO, "application_started", pid=os.getpid())
    startup_ms = (time.monotonic() - startup_started) * 1000

    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(250)

    timing_timer = QTimer()
    timing_timer.timeout.connect(
        lambda: publish(
            ApplicationEventKind.TIMING_TICK,
            "timing_timer",
            TimingTickEvent(
                datetime.now().astimezone(),
                time.monotonic_ns() // 1_000_000,
            ),
        )
    )
    timing_timer.start(1_000)

    if args.smoke_test_duration is not None:
        QTimer.singleShot(
            round(args.smoke_test_duration * 1000),
            lambda: publish(ApplicationEventKind.SHUTDOWN_REQUESTED, "smoke_test"),
        )

    try:
        return application.exec()
    except KeyboardInterrupt:
        application.quit()
        return 130
    finally:
        interrupt_timer.stop()
        timing_timer.stop()
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
