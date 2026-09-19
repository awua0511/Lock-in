"""The sole serialized SQLite connection owner inside the tray process."""

from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from typing import Any, TypeVar, cast

from lock_in.storage.database import open_database

ResultT = TypeVar("ResultT")
DatabaseOperation = Callable[[sqlite3.Connection], ResultT]
_STOP = object()


class DatabaseWorker:
    name = "database"
    _registry_lock = threading.Lock()
    _active_paths: set[Path] = set()

    def __init__(self, path: Path, *, startup_timeout: float = 5.0) -> None:
        self._path = path
        self._resolved_path = path.resolve()
        self._startup_timeout = startup_timeout
        self._queue: queue.Queue[
            tuple[DatabaseOperation[Any], Future[Any]] | object
        ] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._lock = threading.Lock()
        self._state = "new"
        self._writer_thread_id: int | None = None

    @property
    def writer_thread_id(self) -> int | None:
        return self._writer_thread_id

    def start(self) -> None:
        with self._lock:
            if self._state == "running":
                return
            if self._state != "new":
                raise RuntimeError("database worker cannot be restarted")
            with self._registry_lock:
                if self._resolved_path in self._active_paths:
                    raise RuntimeError("database already has an active writer")
                self._active_paths.add(self._resolved_path)
            self._state = "starting"
            self._thread = threading.Thread(
                target=self._run,
                name="lock-in-database",
                daemon=False,
            )
            try:
                self._thread.start()
            except BaseException:
                self._release_path()
                self._state = "stopped"
                raise
        if not self._ready.wait(self._startup_timeout):
            self.stop(self._startup_timeout)
            raise TimeoutError("database worker startup timed out")
        if self._startup_error is not None:
            with self._lock:
                self._state = "stopped"
            raise RuntimeError(
                "database worker initialization failed"
            ) from self._startup_error
        with self._lock:
            self._state = "running"

    def submit(self, operation: DatabaseOperation[ResultT]) -> Future[ResultT]:
        with self._lock:
            if self._state != "running":
                raise RuntimeError("database worker is not running")
            future: Future[ResultT] = Future()
            self._queue.put((operation, future))
            return future

    def stop(self, timeout: float) -> None:
        with self._lock:
            if self._state == "stopped":
                return
            if self._state == "new":
                self._state = "stopped"
                return
            self._state = "stopping"
            thread = self._thread
            self._queue.put(_STOP)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        if thread is not None and thread.is_alive():
            raise TimeoutError("database worker shutdown timed out")
        with self._lock:
            self._state = "stopped"

    def _run(self) -> None:
        connection: sqlite3.Connection | None = None
        try:
            connection = open_database(self._path)
            self._writer_thread_id = threading.get_ident()
        except BaseException as error:
            self._startup_error = error
            self._ready.set()
            self._release_path()
            return
        self._ready.set()
        try:
            while True:
                item = self._queue.get()
                try:
                    if item is _STOP:
                        return
                    operation, future = cast(
                        tuple[DatabaseOperation[Any], Future[Any]], item
                    )
                    if not future.set_running_or_notify_cancel():
                        continue
                    try:
                        future.set_result(operation(connection))
                    except BaseException as error:
                        future.set_exception(error)
                finally:
                    self._queue.task_done()
        finally:
            connection.close()
            self._release_path()

    def _release_path(self) -> None:
        with self._registry_lock:
            self._active_paths.discard(self._resolved_path)
