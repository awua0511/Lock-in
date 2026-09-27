from __future__ import annotations

import logging

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
