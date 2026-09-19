"""Production Lock-In desktop application entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from lock_in.app.config import (
    APPLICATION_NAME,
    APPLICATION_VERSION,
    ORGANIZATION_NAME,
    SHUTDOWN_TIMEOUT_SECONDS,
    application_data_directory,
    log_directory,
)
from lock_in.app.configuration_service import ConfigurationService
from lock_in.app.coordinator import ApplicationCoordinator
from lock_in.app.event_bus import SerializedEventBus
from lock_in.app.events import (
    ApplicationEvent,
    ApplicationEventKind,
    PromptDecisionEvent,
)
from lock_in.app.focus_service import FocusApplicationService
from lock_in.app.lifecycle import ApplicationLifecycle
from lock_in.app.logging_setup import configure_application_logging, safe_log
from lock_in.monitoring.foreground_service import ForegroundMonitoringService
from lock_in.platform.windows.local_identity import (
    SingleInstanceMutex,
    application_mutex_name,
)
from lock_in.platform.windows.window_activation import WindowActivator
from lock_in.rules.application_policy import ApplicationFocusPolicy
from lock_in.storage.database import database_path
from lock_in.storage.repositories import Repositories
from lock_in.storage.worker import DatabaseWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Lock-In desktop application.")
    parser.add_argument(
        "--instance-namespace", default="default", help=argparse.SUPPRESS
    )
    parser.add_argument("--log-directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--data-directory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--no-tray", action="store_true", help=argparse.SUPPRESS)
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
        return _run_application(args, logger)
    finally:
        mutex.close()


def _run_application(args: argparse.Namespace, logger: logging.Logger) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from lock_in.ui.bridge import QtUiBridge
    from lock_in.ui.shell import DesktopShell

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName(APPLICATION_NAME)
    application.setApplicationVersion(APPLICATION_VERSION)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setQuitOnLastWindowClosed(False)

    bridge = QtUiBridge()
    database_worker = DatabaseWorker(
        database_path(args.data_directory or application_data_directory())
    )
    repositories = Repositories.create(database_worker)
    focus_service = FocusApplicationService(
        ApplicationFocusPolicy(),
        repositories.history,
        bridge,
        WindowActivator(),
        logger,
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
    coordinator = ApplicationCoordinator(
        bridge,
        logger,
        configuration=configuration_service,
        focus=focus_service,
    )
    event_bus = SerializedEventBus(coordinator.handle, logger)
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
        (database_worker, configuration_service, focus_service, monitor),
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
        lambda prompt_id, decision: publish(
            ApplicationEventKind.PROMPT_DECIDED,
            "prompt",
            PromptDecisionEvent(prompt_id, decision.value),
        ),
        tray_enabled=not args.no_tray,
    )
    shutdown_lock = threading.Lock()
    shutdown_complete = False

    def shutdown() -> None:
        nonlocal shutdown_complete
        with shutdown_lock:
            if shutdown_complete:
                return
            shutdown_complete = True
        lifecycle.stop(SHUTDOWN_TIMEOUT_SECONDS)
        event_bus.stop(SHUTDOWN_TIMEOUT_SECONDS)
        shell.close()
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

    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(250)

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
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
