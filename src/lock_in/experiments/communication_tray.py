"""Experiment 3 single-instance Named Pipe server (no product features)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path
from typing import Any

from lock_in.communication.protocol import (
    MAX_MESSAGE_BYTES,
    MAX_TEST_DELAY_MS,
    ProtocolError,
    SequenceStatus,
    SequenceTracker,
    decode_message,
    encode_message,
    parse_envelope,
    protocol_error_message,
    response_for,
)
from lock_in.platform.windows.local_identity import (
    SingleInstanceMutex,
    mutex_name,
    pipe_address,
)


@dataclass(slots=True)
class ClientSession:
    connection_id: str | None = None
    client_instance_id: str | None = None
    browser: str | None = None
    handshake_complete: bool = False


class MessageRouter:
    """Route experiment-only hello and ping messages."""

    def __init__(self) -> None:
        self._sequences = SequenceTracker()

    def route(self, message: dict[str, Any], session: ClientSession) -> dict[str, Any]:
        if message.get("type") == "control_shutdown":
            if message.get("connectionId") is not None:
                return protocol_error_message(
                    "control_not_allowed",
                    "Browser connections cannot stop the tray process",
                    reply_to=message.get("messageId")
                    if isinstance(message.get("messageId"), str)
                    else None,
                )
            return {
                "protocolVersion": 1,
                "messageId": str(message.get("messageId", "control")),
                "replyTo": message.get("messageId"),
                "type": "shutdown_ack",
                "status": "accepted",
                "payload": {},
            }

        try:
            request = parse_envelope(message, require_connection=True)
        except ProtocolError as error:
            return protocol_error_message(
                error.code,
                str(error),
                reply_to=message.get("messageId")
                if isinstance(message.get("messageId"), str)
                else None,
                connection_id=message.get("connectionId")
                if isinstance(message.get("connectionId"), str)
                else None,
            )

        if request.message_type == "hello":
            session.connection_id = request.connection_id
            session.client_instance_id = request.client_instance_id
            session.browser = request.browser
            session.handshake_complete = True
            return response_for(
                request,
                "hello_ack",
                status="accepted",
                payload={
                    "serverMonotonicMs": time.monotonic_ns() // 1_000_000,
                    "serverPid": os.getpid(),
                },
            )

        if not session.handshake_complete:
            return protocol_error_message(
                "handshake_required",
                "hello must be accepted before other messages",
                reply_to=request.message_id,
                connection_id=request.connection_id,
            )
        if request.connection_id != session.connection_id:
            return protocol_error_message(
                "connection_mismatch",
                "connectionId changed within one Pipe connection",
                reply_to=request.message_id,
                connection_id=request.connection_id,
            )
        if request.client_instance_id != session.client_instance_id:
            return protocol_error_message(
                "client_mismatch",
                "clientInstanceId changed within one Pipe connection",
                reply_to=request.message_id,
                connection_id=request.connection_id,
            )
        if request.browser != session.browser:
            return protocol_error_message(
                "browser_mismatch",
                "browser changed within one Pipe connection",
                reply_to=request.message_id,
                connection_id=request.connection_id,
            )
        if request.message_type != "ping":
            return protocol_error_message(
                "unknown_message_type",
                "Experiment 3 accepts only hello and ping",
                reply_to=request.message_id,
                connection_id=request.connection_id,
            )

        ordering = self._sequences.observe(
            request.client_instance_id, request.sequence
        )
        delay_ms = request.payload.get("testDelayMs", 0)
        if (
            not isinstance(delay_ms, int)
            or isinstance(delay_ms, bool)
            or not 0 <= delay_ms <= MAX_TEST_DELAY_MS
        ):
            return protocol_error_message(
                "invalid_test_delay",
                f"testDelayMs must be between 0 and {MAX_TEST_DELAY_MS}",
                reply_to=request.message_id,
                connection_id=request.connection_id,
            )
        if delay_ms:
            time.sleep(delay_ms / 1000)

        return response_for(
            request,
            "pong",
            status=ordering.value,
            payload={
                "echo": request.payload.get("echo"),
                "serverMonotonicMs": time.monotonic_ns() // 1_000_000,
            },
        )


class PipeServer:
    def __init__(self, address: str, logger: logging.Logger) -> None:
        self._address = address
        self._logger = logger
        self._stop = threading.Event()
        self._listener: Listener | None = None
        self._connections: set[Connection] = set()
        self._connections_lock = threading.Lock()
        self._handlers: set[threading.Thread] = set()
        self._handlers_lock = threading.Lock()
        self._router = MessageRouter()

    def serve(self, *, duration: float | None = None) -> None:
        self._listener = Listener(self._address, family="AF_PIPE", backlog=16)
        self._logger.info("tray_ready address=%s pid=%s", self._address, os.getpid())
        if duration is not None:
            timer = threading.Timer(duration, self.request_stop)
            timer.daemon = True
            timer.start()
        try:
            while not self._stop.is_set():
                try:
                    connection = self._listener.accept()
                except (OSError, EOFError):
                    if self._stop.is_set():
                        break
                    raise
                with self._connections_lock:
                    self._connections.add(connection)
                thread = threading.Thread(
                    target=self._handle_connection,
                    args=(connection,),
                    name="experiment3-pipe-client",
                    daemon=True,
                )
                with self._handlers_lock:
                    self._handlers.add(thread)
                thread.start()
        finally:
            self.request_stop()
            with self._handlers_lock:
                handlers = list(self._handlers)
            for thread in handlers:
                thread.join(timeout=1)
            self._logger.info("tray_stopped pid=%s", os.getpid())

    def request_stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        listener = self._listener
        if listener is not None:
            # Closing a multiprocessing Pipe listener from another thread does
            # not reliably wake its blocking accept() on Windows. A local
            # connection completes that accept so the server loop can observe
            # the stop event and exit.
            try:
                wake_connection = Client(self._address, family="AF_PIPE")
                wake_connection.close()
            except OSError:
                pass
            try:
                listener.close()
            except OSError:
                pass
        with self._connections_lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass

    def _handle_connection(self, connection: Connection) -> None:
        session = ClientSession()
        try:
            while not self._stop.is_set():
                try:
                    data = connection.recv_bytes(MAX_MESSAGE_BYTES)
                except (EOFError, OSError):
                    return
                try:
                    message = decode_message(data)
                    response = self._router.route(message, session)
                except ProtocolError as error:
                    response = protocol_error_message(error.code, str(error))
                try:
                    connection.send_bytes(encode_message(response))
                except (EOFError, OSError):
                    return
                if message.get("type") == "control_shutdown":
                    self.request_stop()
                    return
        finally:
            connection.close()
            with self._handlers_lock:
                self._handlers.discard(threading.current_thread())
            with self._connections_lock:
                self._connections.discard(connection)


def default_log_path(namespace: str) -> Path:
    override = os.environ.get("LOCK_IN_EXPERIMENT3_LOG_DIR")
    base = (
        Path(override)
        if override
        else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LockIn"
    )
    return base / f"experiment3-{namespace}.log"


def configure_logging(path: Path, *, console: bool) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"lock_in.experiment3.{path}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    return logger


def send_shutdown(namespace: str) -> bool:
    try:
        connection = Client(pipe_address(namespace), family="AF_PIPE")
    except OSError:
        return False
    try:
        connection.send_bytes(
            encode_message(
                {
                    "protocolVersion": 1,
                    "messageId": "control-shutdown",
                    "type": "control_shutdown",
                }
            )
        )
        response = decode_message(connection.recv_bytes())
        return response.get("type") == "shutdown_ack"
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Experiment 3 single-instance Pipe server.",
    )
    parser.add_argument("--namespace", default="default", help=argparse.SUPPRESS)
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--shutdown", action="store_true", help="Stop the running server.")
    parser.add_argument("--duration", type=float, metavar="SECONDS")
    parser.add_argument("--log", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.name != "nt":
        print("Experiment 3 requires Windows.", file=sys.stderr)
        return 2
    if args.duration is not None and args.duration <= 0:
        print("--duration must be greater than zero.", file=sys.stderr)
        return 2
    if args.shutdown:
        stopped = send_shutdown(args.namespace)
        print("stopped" if stopped else "not_running")
        return 0 if stopped else 1

    log_path = args.log or default_log_path(args.namespace)
    logger = configure_logging(log_path, console=not args.background)
    with SingleInstanceMutex(mutex_name(args.namespace)) as mutex:
        if mutex.already_exists:
            logger.info("duplicate_start_rejected pid=%s", os.getpid())
            return 0
        server = PipeServer(pipe_address(args.namespace), logger)
        try:
            server.serve(duration=args.duration)
        except KeyboardInterrupt:
            server.request_stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
