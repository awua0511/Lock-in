"""Production per-user Named Pipe server for Native Messaging relays."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from multiprocessing.connection import Client, Connection, Listener
from typing import Any

from lock_in.communication.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    SequenceTracker,
    decode_message,
    encode_message,
    parse_envelope,
    protocol_error_message,
    response_for,
)


@dataclass(slots=True)
class _Session:
    connection_id: str | None = None
    client_id: str | None = None
    browser: str | None = None
    ready: bool = False
    outgoing_sequence: int = 0
    send_lock: threading.Lock = dataclass_field(default_factory=threading.Lock)
    outbox: queue.Queue = dataclass_field(
        default_factory=lambda: queue.Queue(maxsize=32)
    )
    closed: threading.Event = dataclass_field(default_factory=threading.Event)
    writer: threading.Thread | None = None


class BrowserPipeServer:
    name = "browser_ipc"

    def __init__(
        self,
        address: str,
        message_sink: Callable[[dict[str, Any]], None],
        logger: logging.Logger,
    ) -> None:
        self._address = address
        self._message_sink = message_sink
        self._logger = logger
        self._stop = threading.Event()
        self._listener: Listener | None = None
        self._accept_thread: threading.Thread | None = None
        self._connections: dict[str, Connection] = {}
        self._all_connections: set[Connection] = set()
        self._sessions: dict[str, _Session] = {}
        self._connections_lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._handlers: set[threading.Thread] = set()
        self._handlers_lock = threading.Lock()
        self._sequences = SequenceTracker()

    def start(self) -> None:
        self._listener = Listener(self._address, family="AF_PIPE", backlog=32)
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="browser-pipe-accept", daemon=True
        )
        self._accept_thread.start()

    def stop(self, timeout: float) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        listener = self._listener
        if listener is not None:
            try:
                wake = Client(self._address, family="AF_PIPE")
                wake.close()
            except OSError:
                pass
            try:
                listener.close()
            except OSError:
                pass
        with self._connections_lock:
            connections = tuple(self._all_connections)
            sessions = tuple(self._sessions.values())
            self._connections.clear()
            self._all_connections.clear()
        for session in sessions:
            session.closed.set()
        for connection in connections:
            self._close_connection(connection)
        deadline = time.monotonic() + timeout
        if self._accept_thread is not None:
            self._accept_thread.join(max(0.0, deadline - time.monotonic()))
        with self._handlers_lock:
            handlers = tuple(self._handlers)
        for handler in handlers:
            handler.join(max(0.0, deadline - time.monotonic()))
        for session in sessions:
            if session.writer is not None:
                session.writer.join(max(0.0, deadline - time.monotonic()))

    def send(self, connection_id: str, message: dict[str, Any]) -> bool:
        with self._connections_lock:
            connection = self._connections.get(connection_id)
            session = self._sessions.get(connection_id)
        if connection is None or session is None or session.closed.is_set():
            return False
        try:
            session.outbox.put_nowait(dict(message))
            return True
        except queue.Full:
            # A stopped Host must not hold the serialized application queue.
            session.closed.set()
            self._close_connection(connection)
            return False

    def _write_outbox(self, connection: Connection, session: _Session) -> None:
        try:
            while not self._stop.is_set() and not session.closed.is_set():
                try:
                    message = session.outbox.get(timeout=0.1)
                except queue.Empty:
                    continue
                outgoing = {
                    **message,
                    "clientInstanceId": session.client_id,
                    "browser": session.browser,
                    "connectionId": session.connection_id,
                    "sequence": session.outgoing_sequence,
                }
                session.outgoing_sequence += 1
                with session.send_lock:
                    connection.send_bytes(encode_message(outgoing))
        except (OSError, EOFError, ProtocolError):
            session.closed.set()
            self._close_connection(connection)

    def _close_connection(self, connection: Connection) -> None:
        # Connection.close() checks and clears its handle in separate steps.
        # Stop, reader and writer may all close it concurrently on Windows.
        with self._close_lock:
            try:
                connection.close()
            except OSError:
                pass

    def broadcast(self, browser: str, message: dict[str, Any]) -> tuple[str, ...]:
        with self._connections_lock:
            targets = tuple(
                connection_id
                for connection_id, session in self._sessions.items()
                if session.browser == browser
            )
        return tuple(
            connection_id
            for connection_id in targets
            if self.send(connection_id, message)
        )

    def connections(self) -> tuple[tuple[str, str, str], ...]:
        with self._connections_lock:
            return tuple(
                (connection_id, session.client_id or "", session.browser or "")
                for connection_id, session in self._sessions.items()
                if session.ready
            )

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                connection = self._listener.accept()
            except (OSError, EOFError):
                if not self._stop.is_set():
                    self._logger.exception("browser_pipe_accept_failed")
                return
            with self._connections_lock:
                self._all_connections.add(connection)
            handler = threading.Thread(
                target=self._handle_connection,
                args=(connection,),
                name="browser-pipe-client",
                daemon=True,
            )
            with self._handlers_lock:
                self._handlers.add(handler)
            handler.start()

    def _handle_connection(self, connection: Connection) -> None:
        session = _Session()
        key: str | None = None
        try:
            while not self._stop.is_set():
                raw = connection.recv_bytes(MAX_MESSAGE_BYTES)
                try:
                    message = decode_message(raw)
                    envelope = parse_envelope(message, require_connection=True)
                except ProtocolError as error:
                    with session.send_lock:
                        connection.send_bytes(
                            encode_message(
                                protocol_error_message(error.code, str(error))
                            )
                        )
                    continue

                if envelope.message_type == "hello":
                    if session.ready or envelope.connection_id is None:
                        raise ProtocolError(
                            "duplicate_hello", "hello already completed"
                        )
                    candidate_key = envelope.connection_id
                    with self._connections_lock:
                        if candidate_key in self._sessions:
                            raise ProtocolError(
                                "duplicate_connection", "connectionId is already active"
                            )
                        key = candidate_key
                        session.connection_id = key
                        session.client_id = envelope.client_instance_id
                        session.browser = envelope.browser
                        session.ready = True
                        self._connections[key] = connection
                        self._sessions[key] = session
                    session.writer = threading.Thread(
                        target=self._write_outbox,
                        args=(connection, session),
                        name="browser-pipe-writer",
                        daemon=True,
                    )
                    session.writer.start()
                    response = response_for(
                        envelope,
                        "hello_ack",
                        status="accepted",
                        payload={"serverMonotonicMs": time.monotonic_ns() // 1_000_000},
                    )
                    with session.send_lock:
                        connection.send_bytes(encode_message(response))
                    self._message_sink(
                        {
                            "event": "connected",
                            "connectionId": key,
                            "clientInstanceId": session.client_id,
                            "browser": session.browser,
                        }
                    )
                    continue

                if (
                    not session.ready
                    or envelope.connection_id != session.connection_id
                    or envelope.client_instance_id != session.client_id
                    or envelope.browser != session.browser
                ):
                    raise ProtocolError("session_mismatch", "session identity changed")
                status = self._sequences.observe(
                    envelope.client_instance_id, envelope.sequence
                )
                if envelope.message_type == "browser_context_snapshot":
                    self._message_sink(
                        {
                            "event": "browser_context_snapshot",
                            "connectionId": session.connection_id,
                            "clientInstanceId": session.client_id,
                            "browser": session.browser,
                            "sequence": envelope.sequence,
                            "payload": envelope.payload,
                            "messageId": envelope.message_id,
                        }
                    )
                    response = response_for(
                        envelope, "snapshot_ack", status=status.value
                    )
                elif envelope.message_type == "heartbeat":
                    response = response_for(
                        envelope, "heartbeat_ack", status="accepted"
                    )
                else:
                    response = protocol_error_message(
                        "unknown_message_type",
                        "Production host accepts hello, browser_context_snapshot, and heartbeat",
                        reply_to=envelope.message_id,
                        connection_id=session.connection_id,
                    )
                with session.send_lock:
                    connection.send_bytes(encode_message(response))
        except (EOFError, OSError):
            pass
        except ProtocolError as error:
            try:
                with session.send_lock:
                    connection.send_bytes(
                        encode_message(protocol_error_message(error.code, str(error)))
                    )
            except (EOFError, OSError, ProtocolError):
                pass
        finally:
            session.closed.set()
            if key is not None:
                with self._connections_lock:
                    self._connections.pop(key, None)
                    self._sessions.pop(key, None)
                self._message_sink(
                    {
                        "event": "disconnected",
                        "connectionId": key,
                        "clientInstanceId": session.client_id,
                        "browser": session.browser,
                    }
                )
            self._close_connection(connection)
            with self._connections_lock:
                self._all_connections.discard(connection)
            with self._handlers_lock:
                self._handlers.discard(threading.current_thread())
