"""Stateless Native Messaging-to-Named-Pipe relay for Experiment 3."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from multiprocessing.connection import Client, Connection
from typing import Any, BinaryIO

from lock_in.communication.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    decode_message,
    encode_message,
    parse_envelope,
    protocol_error_message,
)
from lock_in.platform.windows.local_identity import pipe_address

CONNECT_TIMEOUT_SECONDS = 8.0
CONNECT_RETRY_SECONDS = 0.1
CREATE_NO_WINDOW = 0x08000000


def read_native_message(stream: BinaryIO) -> bytes | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ProtocolError("truncated_header", "Native Messaging header is incomplete")
    (length,) = struct.unpack("<I", header)
    if length == 0:
        raise ProtocolError("empty_message", "Native Messaging body is empty")
    if length > MAX_MESSAGE_BYTES:
        raise ProtocolError("message_too_large", "Native Messaging body exceeds 64 KiB")
    body = stream.read(length)
    if len(body) != length:
        raise ProtocolError("truncated_body", "Native Messaging body is incomplete")
    return body


def write_native_message(stream: BinaryIO, body: bytes) -> None:
    if len(body) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message_too_large", "Native Messaging body exceeds 64 KiB")
    stream.write(struct.pack("<I", len(body)))
    stream.write(body)
    stream.flush()


def _launch_tray(namespace: str) -> subprocess.Popen[bytes]:
    command = [
        sys.executable,
        "-m",
        "lock_in.experiments.communication_tray",
        "--background",
        "--namespace",
        namespace,
    ]
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        close_fds=True,
    )


def connect_or_launch(namespace: str) -> Connection:
    address = pipe_address(namespace)
    deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
    launch_process: subprocess.Popen[bytes] | None = None
    last_launch = 0.0
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return Client(address, family="AF_PIPE")
        except OSError as error:
            last_error = error
            now = time.monotonic()
            if launch_process is None or (
                launch_process.poll() is not None and now - last_launch >= 0.25
            ):
                launch_process = _launch_tray(namespace)
                last_launch = now
            time.sleep(CONNECT_RETRY_SECONDS)
    raise ConnectionError(
        "Could not connect to the Lock-In tray process"
    ) from last_error


class NativeRelay:
    def __init__(
        self,
        connection: Connection,
        input_stream: BinaryIO,
        output_stream: BinaryIO,
    ) -> None:
        self._connection = connection
        self._input = input_stream
        self._output = output_stream
        self._connection_id = str(uuid.uuid4())
        self._stop = threading.Event()
        self._output_lock = threading.Lock()

    def run(self) -> int:
        input_thread = threading.Thread(
            target=self._browser_to_pipe,
            name="native-browser-input",
            daemon=True,
        )
        output_thread = threading.Thread(
            target=self._pipe_to_browser,
            name="native-pipe-output",
            daemon=True,
        )
        input_thread.start()
        output_thread.start()
        while not self._stop.wait(0.05):
            if not input_thread.is_alive() or not output_thread.is_alive():
                self._stop.set()
        self._connection.close()
        input_thread.join(timeout=0.5)
        output_thread.join(timeout=0.5)
        return 0

    def _browser_to_pipe(self) -> None:
        try:
            while not self._stop.is_set():
                body = read_native_message(self._input)
                if body is None:
                    return
                message: dict[str, Any] = {}
                try:
                    message = decode_message(body)
                    parse_envelope(message, require_connection=False)
                except ProtocolError as error:
                    self._write_error(error, message)
                    continue
                message["connectionId"] = self._connection_id
                if message.get("type") == "test_host_crash":
                    os._exit(70)
                self._connection.send_bytes(encode_message(message))
        except (EOFError, OSError, ProtocolError) as error:
            if isinstance(error, ProtocolError):
                self._write_error(error, {})
        finally:
            self._stop.set()

    def _pipe_to_browser(self) -> None:
        try:
            while not self._stop.is_set():
                body = self._connection.recv_bytes(MAX_MESSAGE_BYTES)
                # Decode before forwarding so malformed server output never reaches a browser.
                encode_message(decode_message(body))
                with self._output_lock:
                    write_native_message(self._output, body)
        except (EOFError, OSError, ProtocolError):
            if not self._stop.is_set():
                message = protocol_error_message(
                    "host_unavailable",
                    "The tray process disconnected",
                    connection_id=self._connection_id,
                )
                try:
                    with self._output_lock:
                        write_native_message(self._output, encode_message(message))
                except (OSError, ProtocolError):
                    pass
        finally:
            self._stop.set()

    def _write_error(self, error: ProtocolError, source: dict[str, Any]) -> None:
        message = protocol_error_message(
            error.code,
            str(error),
            reply_to=source.get("messageId")
            if isinstance(source.get("messageId"), str)
            else None,
            connection_id=self._connection_id,
        )
        try:
            with self._output_lock:
                write_native_message(self._output, encode_message(message))
        except OSError:
            self._stop.set()


def main(_argv: Sequence[str] | None = None) -> int:
    if os.name != "nt":
        return 2
    namespace = os.environ.get("LOCK_IN_EXPERIMENT3_NAMESPACE", "default")
    try:
        connection = connect_or_launch(namespace)
    except (ConnectionError, OSError):
        message = protocol_error_message(
            "host_unavailable", "Could not start or connect to the tray process"
        )
        try:
            write_native_message(sys.stdout.buffer, encode_message(message))
        except OSError:
            pass
        return 1
    return NativeRelay(connection, sys.stdin.buffer, sys.stdout.buffer).run()


if __name__ == "__main__":
    raise SystemExit(main())
