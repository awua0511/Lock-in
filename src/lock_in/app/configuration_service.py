"""Asynchronous configuration persistence and in-memory snapshot updates."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Protocol

from lock_in.app.logging_setup import safe_log
from lock_in.domain.models import ApplicationAllowlistEntry, Schedule
from lock_in.rules.application_policy import FocusConfiguration
from lock_in.storage.repositories import Repositories


class ConfigurationSink(Protocol):
    def update_focus_configuration(self, configuration: FocusConfiguration) -> None: ...

    def report_operation_error(self, operation: str) -> None: ...


class ConfigurationService:
    name = "configuration"

    def __init__(
        self,
        repositories: Repositories,
        policy_update: ConfigurationSink,
        ui: ConfigurationSink,
        logger: logging.Logger,
        publish_configuration: Callable[[FocusConfiguration], None],
    ) -> None:
        self._repositories = repositories
        self._policy_update = policy_update
        self._ui = ui
        self._logger = logger
        self._publish_configuration = publish_configuration
        self._lock = threading.Lock()
        self._generation = 0
        self._stopped = False

    def start(self) -> None:
        schedules = self._repositories.schedules.list_all().result(timeout=3)
        applications = self._repositories.allowlist.list_applications().result(
            timeout=3
        )
        self._apply(FocusConfiguration(schedules, applications))

    def stop(self, timeout: float) -> None:
        del timeout
        with self._lock:
            self._stopped = True
            self._generation += 1

    def save_schedule(self, schedule: Schedule) -> None:
        self._after_write(self._repositories.schedules.save(schedule), "save_schedule")

    def delete_schedule(self, schedule_id: str) -> None:
        self._after_write(
            self._repositories.schedules.delete(schedule_id), "delete_schedule"
        )

    def save_application(self, entry: ApplicationAllowlistEntry) -> None:
        self._after_write(
            self._repositories.allowlist.save_application(entry),
            "save_application_allowlist",
        )

    def delete_application(self, entry_id: str) -> None:
        self._after_write(
            self._repositories.allowlist.delete_application(entry_id),
            "delete_application_allowlist",
        )

    def reload_async(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._generation += 1
            generation = self._generation
        schedule_future = self._repositories.schedules.list_all()
        application_future = self._repositories.allowlist.list_applications()
        results: dict[str, object] = {}
        results_lock = threading.Lock()

        def complete(name: str, future: Future[object]) -> None:
            try:
                result = future.result()
            except BaseException as error:
                self._report_failure("reload_configuration", error)
                return
            with results_lock:
                results[name] = result
                if len(results) != 2:
                    return
                schedules = results["schedules"]
                applications = results["applications"]
            with self._lock:
                if self._stopped or generation != self._generation:
                    return
            self._publish_configuration(
                FocusConfiguration(schedules, applications)  # type: ignore[arg-type]
            )

        schedule_future.add_done_callback(lambda future: complete("schedules", future))
        application_future.add_done_callback(
            lambda future: complete("applications", future)
        )

    def _after_write(self, future: Future[object], operation: str) -> None:
        def complete(completed: Future[object]) -> None:
            try:
                completed.result()
            except BaseException as error:
                self._report_failure(operation, error)
                return
            self.reload_async()

        future.add_done_callback(complete)

    def _apply(self, configuration: FocusConfiguration) -> None:
        self._policy_update.update_focus_configuration(configuration)
        self._ui.update_focus_configuration(configuration)

    def _report_failure(self, operation: str, error: BaseException) -> None:
        safe_log(
            self._logger,
            logging.ERROR,
            "configuration_operation_failed",
            component="configuration",
            operation=operation,
            exception_type=type(error).__name__,
        )
        self._ui.report_operation_error(operation)
