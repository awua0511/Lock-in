from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from lock_in.app.coordinator import ApplicationCoordinator
from lock_in.app.event_bus import SerializedEventBus
from lock_in.app.events import ApplicationEvent, ApplicationEventKind
from lock_in.app.lifecycle import ApplicationLifecycle
from lock_in.app.logging_setup import configure_application_logging, safe_log


class FakeUi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []
        self.called = threading.Event()

    def show_main_window(self) -> None:
        self._record("show", None)

    def request_quit(self) -> None:
        self._record("quit", None)

    def report_component_failure(self, component: str) -> None:
        self._record("failure", component)

    def _record(self, action: str, value: str | None) -> None:
        self.calls.append((action, value, threading.get_ident()))
        self.called.set()


def test_synthetic_event_reaches_coordinator_on_dispatcher_thread(
    tmp_path: Path,
) -> None:
    ui = FakeUi()
    logger = configure_application_logging(tmp_path)
    coordinator = ApplicationCoordinator(ui, logger)
    bus = SerializedEventBus(coordinator.handle, logger)
    caller_thread = threading.get_ident()

    bus.start()
    assert bus.publish(
        ApplicationEvent(
            kind=ApplicationEventKind.SHOW_MAIN_WINDOW,
            source="test",
        )
    )
    assert ui.called.wait(1)
    assert bus.stop(1)

    assert ui.calls[0][:2] == ("show", None)
    assert ui.calls[0][2] == bus.worker_thread_id
    assert ui.calls[0][2] != caller_thread


@dataclass
class FakeComponent:
    name: str
    actions: list[str]
    fail_start: bool = False
    fail_stop: bool = False

    def start(self) -> None:
        self.actions.append(f"start:{self.name}")
        if self.fail_start:
            raise RuntimeError("sensitive start detail")

    def stop(self, timeout: float) -> None:
        self.actions.append(f"stop:{self.name}:{timeout}")
        if self.fail_stop:
            raise RuntimeError("sensitive stop detail")


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[ApplicationEvent] = []

    def publish(self, event: ApplicationEvent) -> bool:
        self.events.append(event)
        return True


def test_lifecycle_continues_after_failures_and_stops_in_reverse_order(
    tmp_path: Path,
) -> None:
    actions: list[str] = []
    publisher = RecordingPublisher()
    lifecycle = ApplicationLifecycle(
        (
            FakeComponent("monitor", actions),
            FakeComponent("ipc", actions, fail_start=True),
            FakeComponent("worker", actions, fail_stop=True),
        ),
        publisher,
        configure_application_logging(tmp_path),
    )

    lifecycle.start()
    lifecycle.start()
    lifecycle.stop(0.25)
    lifecycle.stop(0.25)

    assert actions == [
        "start:monitor",
        "start:ipc",
        "start:worker",
        "stop:worker:0.25",
        "stop:monitor:0.25",
    ]
    assert [event.field("component") for event in publisher.events] == [
        "ipc",
        "worker",
    ]
    assert [event.field("operation") for event in publisher.events] == [
        "start",
        "stop",
    ]


def test_privacy_safe_logging_rejects_arbitrary_fields(tmp_path: Path) -> None:
    logger = configure_application_logging(tmp_path)

    with pytest.raises(ValueError, match="unsafe log fields"):
        safe_log(
            logger,
            logging.INFO,
            "application_event",
            window_title="private",
        )
    with pytest.raises(ValueError, match="unknown log code"):
        safe_log(logger, logging.INFO, "private content")

    safe_log(
        logger,
        logging.ERROR,
        "component_failed",
        component="monitor",
        exception_type="RuntimeError",
    )
    for handler in logger.handlers:
        handler.flush()
    contents = (tmp_path / "lock-in.log").read_text(encoding="utf-8")
    assert "component_failed" in contents
    assert "sensitive start detail" not in contents
