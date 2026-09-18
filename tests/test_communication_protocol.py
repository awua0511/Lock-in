from __future__ import annotations

import io
import struct

import pytest

from lock_in.communication.protocol import (
    MAX_MESSAGE_BYTES,
    ProtocolError,
    SequenceStatus,
    SequenceTracker,
    decode_message,
    encode_message,
    parse_envelope,
)
from lock_in.experiments.communication_tray import ClientSession, MessageRouter
from lock_in.native_host.main import read_native_message, write_native_message


def message(
    message_type: str,
    sequence: int,
    *,
    message_id: str = "message-1",
    client_id: str = "profile-1",
    connection_id: str = "host-1",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "messageId": message_id,
        "type": message_type,
        "clientInstanceId": client_id,
        "browser": "chrome",
        "sequence": sequence,
        "connectionId": connection_id,
        "payload": payload or {},
    }


def test_json_encoding_is_bounded_and_round_trips() -> None:
    original = message("hello", 0)

    assert decode_message(encode_message(original)) == original

    with pytest.raises(ProtocolError, match="64 KiB"):
        encode_message({"value": "x" * MAX_MESSAGE_BYTES})


def test_native_messaging_framing_round_trips() -> None:
    stream = io.BytesIO()
    body = encode_message(message("hello", 0))

    write_native_message(stream, body)
    stream.seek(0)

    assert read_native_message(stream) == body
    assert read_native_message(stream) is None


def test_native_messaging_rejects_oversized_length_before_body() -> None:
    stream = io.BytesIO(struct.pack("<I", MAX_MESSAGE_BYTES + 1))

    with pytest.raises(ProtocolError) as error:
        read_native_message(stream)

    assert error.value.code == "message_too_large"


def test_envelope_rejects_browser_chosen_connection_when_missing_from_host() -> None:
    value = message("hello", 0)
    value.pop("connectionId")

    parsed = parse_envelope(value, require_connection=False)

    assert parsed.connection_id is None
    with pytest.raises(ProtocolError) as error:
        parse_envelope(value, require_connection=True)
    assert error.value.code == "missing_connection"


def test_sequence_tracker_classifies_duplicate_and_out_of_order() -> None:
    tracker = SequenceTracker()

    assert tracker.observe("profile", 10) == SequenceStatus.ACCEPTED
    assert tracker.observe("profile", 10) == SequenceStatus.DUPLICATE
    assert tracker.observe("profile", 9) == SequenceStatus.OUT_OF_ORDER
    assert tracker.observe("profile", 11) == SequenceStatus.ACCEPTED


def test_sequence_tracking_is_independent_between_profiles() -> None:
    tracker = SequenceTracker()

    assert tracker.observe("profile-a", 50) == SequenceStatus.ACCEPTED
    assert tracker.observe("profile-b", 1) == SequenceStatus.ACCEPTED


def test_router_requires_hello_before_ping() -> None:
    router = MessageRouter()

    response = router.route(message("ping", 1), ClientSession())

    assert response["type"] == "protocol_error"
    assert response["payload"]["code"] == "handshake_required"


def test_router_round_trip_and_ordering_statuses() -> None:
    router = MessageRouter()
    session = ClientSession()

    hello = router.route(message("hello", 0), session)
    accepted = router.route(message("ping", 2, message_id="ping-2"), session)
    duplicate = router.route(message("ping", 2, message_id="ping-2b"), session)
    old = router.route(message("ping", 1, message_id="ping-1"), session)

    assert hello["type"] == "hello_ack"
    assert accepted["type"] == "pong"
    assert accepted["status"] == "accepted"
    assert duplicate["status"] == "duplicate"
    assert old["status"] == "out_of_order"


def test_router_rejects_identity_change_on_same_connection() -> None:
    router = MessageRouter()
    session = ClientSession()
    router.route(message("hello", 0), session)

    response = router.route(message("ping", 1, client_id="profile-2"), session)

    assert response["type"] == "protocol_error"
    assert response["payload"]["code"] == "client_mismatch"


def test_router_echoes_payload_without_business_logic() -> None:
    router = MessageRouter()
    session = ClientSession()
    router.route(message("hello", 0), session)

    response = router.route(message("ping", 1, payload={"echo": "round-trip"}), session)

    assert response["payload"]["echo"] == "round-trip"
