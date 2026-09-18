"""End-to-end subprocess harness for the Experiment 3 communication chain."""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lock_in.communication.protocol import encode_message
from lock_in.experiments.communication_tray import send_shutdown
from lock_in.native_host.main import read_native_message, write_native_message


class HarnessFailure(RuntimeError):
    pass


class HostClient:
    def __init__(self, namespace: str) -> None:
        environment = os.environ.copy()
        environment["LOCK_IN_EXPERIMENT3_NAMESPACE"] = namespace
        environment["LOCK_IN_EXPERIMENT3_LOG_DIR"] = str(
            Path.cwd() / ".experiment3-harness"
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "lock_in.native_host.main"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise HarnessFailure("Could not open Native Host stdio")
        self._responses: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def send(self, message: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise HarnessFailure("Native Host stdin is closed")
        write_native_message(self.process.stdin, encode_message(message))

    def receive(self, timeout: float = 10.0) -> dict[str, Any]:
        try:
            result = self._responses.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("Timed out waiting for Native Host response") from error
        if isinstance(result, BaseException):
            raise HarnessFailure(f"Native Host output failed: {result}") from result
        return result

    def expect_no_response(self, timeout: float) -> None:
        try:
            result = self._responses.get(timeout=timeout)
        except queue.Empty:
            return
        raise HarnessFailure(f"Expected a client-side timeout, received: {result}")

    def crash(self) -> None:
        self.process.kill()
        self.process.wait(timeout=5)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)

    def _read_loop(self) -> None:
        assert self.process.stdout is not None
        try:
            while True:
                body = read_native_message(self.process.stdout)
                if body is None:
                    return
                self._responses.put(json.loads(body.decode("utf-8")))
        except BaseException as error:
            self._responses.put(error)


def envelope(
    message_type: str,
    client_id: str,
    browser: str,
    sequence: int,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocolVersion": 1,
        "messageId": str(uuid.uuid4()),
        "type": message_type,
        "clientInstanceId": client_id,
        "browser": browser,
        "sequence": sequence,
        "payload": payload or {},
    }


def assert_response(
    response: dict[str, Any], expected_type: str, expected_status: str
) -> None:
    if response.get("type") != expected_type or response.get("status") != expected_status:
        raise HarnessFailure(
            f"Expected {expected_type}/{expected_status}, received {response}"
        )


def hello(client: HostClient, client_id: str, browser: str) -> dict[str, Any]:
    client.send(envelope("hello", client_id, browser, 0))
    response = client.receive()
    assert_response(response, "hello_ack", "accepted")
    return response


def emit(check: str, **details: object) -> None:
    print(json.dumps({"check": check, "result": "passed", **details}, sort_keys=True))


def run_harness(namespace: str) -> None:
    clients: list[HostClient] = []
    send_shutdown(namespace)
    try:
        # Simultaneous Hosts race to launch the absent tray process.
        chrome = HostClient(namespace)
        edge = HostClient(namespace)
        clients.extend([chrome, edge])
        chrome.send(envelope("hello", "chrome-profile-a", "chrome", 0))
        edge.send(envelope("hello", "edge-profile-a", "edge", 0))
        chrome_hello = chrome.receive()
        edge_hello = edge.receive()
        assert_response(chrome_hello, "hello_ack", "accepted")
        assert_response(edge_hello, "hello_ack", "accepted")
        first_pid = chrome_hello["payload"]["serverPid"]
        if edge_hello["payload"]["serverPid"] != first_pid:
            raise HarnessFailure("Concurrent Hosts connected to different tray processes")
        emit("absent_tray_and_simultaneous_host_start", serverPid=first_pid)

        # Additional profiles get independent Host and Pipe connections.
        chrome_profile_b = HostClient(namespace)
        edge_profile_b = HostClient(namespace)
        clients.extend([chrome_profile_b, edge_profile_b])
        hello(chrome_profile_b, "chrome-profile-b", "chrome")
        hello(edge_profile_b, "edge-profile-b", "edge")
        for client, client_id, browser in [
            (chrome, "chrome-profile-a", "chrome"),
            (edge, "edge-profile-a", "edge"),
            (chrome_profile_b, "chrome-profile-b", "chrome"),
            (edge_profile_b, "edge-profile-b", "edge"),
        ]:
            client.send(
                envelope("ping", client_id, browser, 1, payload={"echo": client_id})
            )
            response = client.receive()
            assert_response(response, "pong", "accepted")
            if response["payload"]["echo"] != client_id:
                raise HarnessFailure("Round-trip echo was changed")
        emit("chrome_edge_multiple_profiles")

        # Duplicate and out-of-order messages receive explicit acknowledgements.
        chrome.send(envelope("ping", "chrome-profile-a", "chrome", 2))
        assert_response(chrome.receive(), "pong", "accepted")
        chrome.send(envelope("ping", "chrome-profile-a", "chrome", 2))
        assert_response(chrome.receive(), "pong", "duplicate")
        chrome.send(envelope("ping", "chrome-profile-a", "chrome", 1))
        assert_response(chrome.receive(), "pong", "out_of_order")
        emit("duplicate_and_out_of_order")

        # The caller times out, then the same full-chain response arrives late.
        edge.send(
            envelope(
                "ping",
                "edge-profile-a",
                "edge",
                2,
                payload={"testDelayMs": 500, "echo": "late"},
            )
        )
        edge.expect_no_response(0.1)
        late = edge.receive(timeout=2)
        assert_response(late, "pong", "accepted")
        emit("timeout_and_late_response")

        # Killing one Host must not affect the tray or other profiles.
        chrome_profile_b.crash()
        replacement = HostClient(namespace)
        clients.append(replacement)
        hello(replacement, "chrome-profile-b", "chrome")
        replacement.send(envelope("ping", "chrome-profile-b", "chrome", 2))
        assert_response(replacement.receive(), "pong", "accepted")
        emit("host_crash_and_extension_reconnect")

        # Stop the tray; a new Host must launch a new single instance.
        if not send_shutdown(namespace):
            raise HarnessFailure("Could not stop tray for restart test")
        restart_deadline = time.monotonic() + 15
        restarted = None
        restarted_hello = None
        while time.monotonic() < restart_deadline:
            candidate = HostClient(namespace)
            clients.append(candidate)
            candidate.send(
                envelope("hello", "edge-profile-reloaded", "edge", 0)
            )
            response = candidate.receive(timeout=10)
            if response.get("type") == "hello_ack":
                restarted = candidate
                restarted_hello = response
                break
            candidate.close()
            time.sleep(0.25)
        if restarted is None or restarted_hello is None:
            raise HarnessFailure("Extension reconnect did not reach the restarted tray")
        assert_response(restarted_hello, "hello_ack", "accepted")
        second_pid = restarted_hello["payload"]["serverPid"]
        if second_pid == first_pid:
            raise HarnessFailure("Tray PID did not change after restart")
        restarted.send(envelope("ping", "edge-profile-reloaded", "edge", 1))
        assert_response(restarted.receive(), "pong", "accepted")
        emit("tray_restart_and_extension_reload", serverPid=second_pid)
    finally:
        for client in clients:
            client.close()
        send_shutdown(namespace)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Experiment 3 end-to-end subprocess checks.",
    )
    parser.add_argument("--namespace", default=f"harness-{uuid.uuid4()}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if os.name != "nt":
        print("Experiment 3 requires Windows.", file=sys.stderr)
        return 2
    try:
        run_harness(args.namespace)
    except (HarnessFailure, OSError, TimeoutError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    print("Experiment 3 automated communication checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
