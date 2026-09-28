"""A single serialized queue for production application events."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable

from lock_in.app.events import ApplicationEvent
from lock_in.app.logging_setup import safe_log

EventHandler = Callable[[ApplicationEvent], None]


class SerializedEventBus:
    def __init__(
        self, handler: EventHandler, logger: logging.Logger, *, measure: bool = False
    ) -> None:
        self._handler = handler
        self._logger = logger
        self._queue: queue.Queue[ApplicationEvent | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._accepting = False
        self._measure = measure
        self._latencies: deque[float] = deque(maxlen=2048)
        self._handled_count = 0
        self._max_handler_ms = 0.0

    def measurements(self) -> dict[str, int | float]:
        values = sorted(self._latencies)
        return {
            "handled_events": self._handled_count,
            "sample_count": len(values),
            "queue_latency_p95_ms": values[
                min(len(values) - 1, int(len(values) * 0.95))
            ]
            if values
            else 0,
            "queue_latency_max_ms": max(values, default=0),
            "handler_max_ms": self._max_handler_ms,
        }

    @property
    def worker_thread_id(self) -> int | None:
        thread = self._thread
        return thread.ident if thread else None

    def start(self) -> None:
        with self._lock:
            if self._accepting:
                return
            self._accepting = True
            self._thread = threading.Thread(
                target=self._run,
                name="lock-in-event-dispatcher",
                daemon=False,
            )
            self._thread.start()

    def publish(self, event: ApplicationEvent) -> bool:
        with self._lock:
            if not self._accepting:
                return False
            self._queue.put(event)
            return True

    def stop(self, timeout: float) -> bool:
        with self._lock:
            if not self._accepting:
                return True
            self._accepting = False
            thread = self._thread
            self._queue.put(None)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            try:
                if event is None:
                    return
                started = time.monotonic_ns() if self._measure else 0
                if self._measure:
                    self._latencies.append(
                        max(0, (started - event.monotonic_ns) / 1_000_000)
                    )
                try:
                    self._handler(event)
                except Exception as error:  # fail open at the component boundary
                    safe_log(
                        self._logger,
                        logging.ERROR,
                        "event_handler_failed",
                        component="coordinator",
                        event_kind=event.kind.value,
                        exception_type=type(error).__name__,
                    )
                finally:
                    if self._measure:
                        self._handled_count += 1
                        self._max_handler_ms = max(
                            self._max_handler_ms,
                            (time.monotonic_ns() - started) / 1_000_000,
                        )
            finally:
                self._queue.task_done()
