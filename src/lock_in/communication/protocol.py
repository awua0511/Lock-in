"""Experiment 3 message validation and ordering rules."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
MAX_TEST_DELAY_MS = 5_000


class ProtocolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SequenceStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"


class SequenceTracker:
    """Track the highest sequence for each persistent extension identity."""

    def __init__(self) -> None:
        self._last_by_client: dict[str, int] = {}
        self._lock = threading.Lock()

    def observe(self, client_instance_id: str, sequence: int) -> SequenceStatus:
        with self._lock:
            previous = self._last_by_client.get(client_instance_id)
            if previous is not None:
                if sequence == previous:
                    return SequenceStatus.DUPLICATE
                if sequence < previous:
                    return SequenceStatus.OUT_OF_ORDER
            self._last_by_client[client_instance_id] = sequence
            return SequenceStatus.ACCEPTED


@dataclass(frozen=True, slots=True)
class Envelope:
    protocol_version: int
    message_id: str
    message_type: str
    client_instance_id: str
    browser: str
    sequence: int
    connection_id: str | None
    payload: dict[str, Any]


def encode_message(message: dict[str, Any]) -> bytes:
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message_too_large", "Message exceeds 64 KiB")
    return encoded


def decode_message(data: bytes) -> dict[str, Any]:
    if not data:
        raise ProtocolError("empty_message", "Message is empty")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message_too_large", "Message exceeds 64 KiB")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(
            "invalid_json", "Message is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise ProtocolError("invalid_envelope", "Message must be a JSON object")
    return value


def parse_envelope(message: dict[str, Any], *, require_connection: bool) -> Envelope:
    version = message.get("protocolVersion")
    if version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_version", "Unsupported protocol version")

    def required_string(name: str) -> str:
        value = message.get(name)
        if not isinstance(value, str) or not value or len(value) > 128:
            raise ProtocolError(
                "invalid_envelope", f"{name} must be a non-empty string"
            )
        return value

    message_id = required_string("messageId")
    message_type = required_string("type")
    client_instance_id = required_string("clientInstanceId")
    browser = required_string("browser")
    if browser not in {"chrome", "edge"}:
        raise ProtocolError("invalid_browser", "browser must be chrome or edge")

    sequence = message.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ProtocolError(
            "invalid_sequence", "sequence must be a non-negative integer"
        )

    connection_id = message.get("connectionId")
    if require_connection and (not isinstance(connection_id, str) or not connection_id):
        raise ProtocolError("missing_connection", "Host connectionId is required")
    if connection_id is not None and not isinstance(connection_id, str):
        raise ProtocolError("invalid_connection", "connectionId must be a string")

    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_payload", "payload must be an object")

    return Envelope(
        protocol_version=version,
        message_id=message_id,
        message_type=message_type,
        client_instance_id=client_instance_id,
        browser=browser,
        sequence=sequence,
        connection_id=connection_id,
        payload=payload,
    )


def response_for(
    request: Envelope,
    response_type: str,
    *,
    status: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": request.message_id,
        "replyTo": request.message_id,
        "type": response_type,
        "clientInstanceId": request.client_instance_id,
        "browser": request.browser,
        "sequence": request.sequence,
        "connectionId": request.connection_id,
        "status": status,
        "payload": payload or {},
    }


def protocol_error_message(
    code: str,
    message: str,
    *,
    reply_to: str | None = None,
    connection_id: str | None = None,
) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "messageId": reply_to or "protocol-error",
        "replyTo": reply_to,
        "type": "protocol_error",
        "connectionId": connection_id,
        "status": "rejected",
        "payload": {"code": code, "message": message},
    }
