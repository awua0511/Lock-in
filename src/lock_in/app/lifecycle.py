"""Bounded startup and reverse-order shutdown for application services."""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from lock_in.app.events import ApplicationEvent
from lock_in.app.logging_setup import safe_log


class EventPublisher(Protocol):
    def publish(self, event: ApplicationEvent) -> bool: ...


class ManagedComponent(Protocol):
    @property
    def name(self) -> str: ...

    def start(self) -> None: ...

    def stop(self, timeout: float) -> None: ...


class ApplicationLifecycle:
    def __init__(
        self,
        components: tuple[ManagedComponent, ...],
        publisher: EventPublisher,
        logger: logging.Logger,
    ) -> None:
        self._components = components
        self._publisher = publisher
        self._logger = logger
        self._started: list[ManagedComponent] = []
        self._lock = threading.Lock()
        self._start_called = False
        self._stopped = False

    def start(self) -> None:
        with self._lock:
            if self._start_called or self._stopped:
                return
            self._start_called = True
        for component in self._components:
            try:
                component.start()
            except Exception as error:  # each service is an isolation boundary
                self._report_failure(component.name, "start", error)
                continue
            self._started.append(component)
            safe_log(
                self._logger,
                logging.INFO,
                "component_started",
                component=component.name,
            )

    def stop(self, timeout: float) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            components = tuple(reversed(self._started))
        for component in components:
            try:
                component.stop(timeout)
            except Exception as error:  # shutdown must continue after a failure
                self._report_failure(component.name, "stop", error)
                continue
            safe_log(
                self._logger,
                logging.INFO,
                "component_stopped",
                component=component.name,
            )

    def _report_failure(
        self, component: str, operation: str, error: BaseException
    ) -> None:
        safe_log(
            self._logger,
            logging.ERROR,
            "component_failed",
            component=component,
            operation=operation,
            exception_type=type(error).__name__,
        )
        self._publisher.publish(
            ApplicationEvent.component_failed(component, operation, error)
        )
