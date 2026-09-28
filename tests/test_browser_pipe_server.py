from __future__ import annotations

import logging
import os
import queue
import threading
import uuid
from multiprocessing.connection import Client

import pytest

from lock_in.communication.protocol import decode_message, encode_message
from lock_in.ipc.pipe_server import BrowserPipeServer, _Session


class _FakeConnection:
    def __init__(self, messages: list[bytes]) -> None:
        self.messages = iter(messages)
        self.sent: list[bytes] = []

    def recv_bytes(self, _limit: int) -> bytes:
        try:
            return next(self.messages)
        except StopIteration as error:
            raise EOFError from error

    def send_bytes(self, message: bytes) -> None:
        self.sent.append(message)

    def close(self) -> None:
        pass


def test_duplicate_connection_id_does_not_remove_active_session() -> None:
    server = BrowserPipeServer("unused", lambda _event: None, logging.getLogger())
    existing_connection = _FakeConnection([])
    existing_session = _Session(
        connection_id="same-id",
        client_id="profile-a",
        browser="chrome",
        ready=True,
    )
    server._connections["same-id"] = existing_connection  # noqa: SLF001
    server._all_connections.add(existing_connection)  # noqa: SLF001
    server._sessions["same-id"] = existing_session  # noqa: SLF001

    duplicate = _FakeConnection(
        [
            encode_message(
                {
                    "protocolVersion": 1,
                    "messageId": "hello-id",
                    "type": "hello",
                    "clientInstanceId": "profile-b",
                    "browser": "edge",
                    "sequence": 0,
                    "connectionId": "same-id",
                    "payload": {},
                }
            )
        ]
    )

    server._handle_connection(duplicate)  # noqa: SLF001

    assert server._connections["same-id"] is existing_connection  # noqa: SLF001
    assert server._sessions["same-id"] is existing_session  # noqa: SLF001
    response = decode_message(duplicate.sent[0])
    assert response["payload"]["code"] == "duplicate_connection"


def test_a_stalled_host_cannot_block_the_application_event_thread():
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()

    class StalledConnection(_FakeConnection):
        def send_bytes(self, _message):
            entered.set()
            release.wait(2)

    connection = StalledConnection([])
    server = BrowserPipeServer("unused", lambda _event: None, logging.getLogger())
    session = _Session(connection_id="a", client_id="p", browser="chrome", ready=True)
    server._connections["a"] = connection
    server._sessions["a"] = session
    writer = threading.Thread(
        target=server._write_outbox, args=(connection, session), daemon=True
    )
    writer.start()
    caller = threading.Thread(
        target=lambda: (server.send("a", {"type": "request_snapshot"}), returned.set()),
        daemon=True,
    )
    try:
        caller.start()
        assert returned.wait(0.5)
        assert entered.wait(0.5)
        assert not release.is_set()
    finally:
        session.closed.set()
        release.set()
        caller.join(2)
        writer.join(2)


def test_outgoing_queue_is_bounded_for_an_unresponsive_host():
    connection = _FakeConnection([])
    server = BrowserPipeServer("unused", lambda _event: None, logging.getLogger())
    session = _Session(connection_id="a", client_id="p", browser="chrome", ready=True)
    server._connections["a"] = connection
    server._sessions["a"] = session
    assert all(server.send("a", {"type": "request_snapshot"}) for _ in range(32))
    assert not server.send("a", {"type": "request_snapshot"})
    assert session.closed.is_set()


@pytest.mark.skipif(os.name != "nt", reason="Windows Named Pipe integration")
def test_production_pipe_round_trip_with_two_profiles_and_restart():
    address = rf"\\.\pipe\LockIn.audit.{uuid.uuid4().hex}"
    for _restart in range(2):
        events = queue.Queue()
        server = BrowserPipeServer(address, events.put, logging.getLogger())
        clients = []
        server.start()
        try:
            for index, browser in enumerate(("chrome", "edge")):
                client = Client(address, family="AF_PIPE")
                clients.append(client)
                hello = {
                    "protocolVersion": 1,
                    "messageId": f"hello-{index}",
                    "type": "hello",
                    "clientInstanceId": f"profile-{index}",
                    "browser": browser,
                    "sequence": 0,
                    "connectionId": f"host-{index}",
                    "payload": {},
                }
                client.send_bytes(encode_message(hello))
                assert client.poll(2), "hello acknowledgement timed out"
                assert decode_message(client.recv_bytes())["type"] == "hello_ack"
                assert events.get(timeout=2)["event"] == "connected"
            assert len(server.connections()) == 2
            for index, client in enumerate(clients):
                assert server.send(
                    f"host-{index}",
                    {
                        "protocolVersion": 1,
                        "messageId": f"request-{index}",
                        "type": "request_snapshot",
                        "payload": {"foregroundEpoch": 1},
                    },
                )
                assert client.poll(2), "outbox did not deliver request"
                request = decode_message(client.recv_bytes())
                assert request["clientInstanceId"] == f"profile-{index}"
                client.send_bytes(
                    encode_message(
                        {
                            **request,
                            "type": "browser_context_snapshot",
                            "sequence": 1,
                        }
                    )
                )
                assert client.poll(2), "snapshot acknowledgement timed out"
                assert decode_message(client.recv_bytes())["type"] == "snapshot_ack"
                event = events.get(timeout=2)
                assert event["connectionId"] == f"host-{index}"
                assert event["event"] == "browser_context_snapshot"
        finally:
            for client in clients:
                client.close()
            server.stop(3)
        assert not server._accept_thread.is_alive()
        assert not server.connections()
