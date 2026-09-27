"""Production Native Messaging entry point used by installed browser extensions."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from lock_in.communication.protocol import (
    encode_message,
    protocol_error_message,
)
from lock_in.native_host.main import (
    NativeRelay,
    connect_or_launch,
    write_native_message,
)


def main(_argv: Sequence[str] | None = None) -> int:
    if os.name != "nt":
        return 2
    namespace = os.environ.get("LOCK_IN_NAMESPACE", "default")
    try:
        connection = connect_or_launch(namespace, production=True)
    except (ConnectionError, OSError):
        try:
            write_native_message(
                sys.stdout.buffer,
                encode_message(
                    protocol_error_message(
                        "host_unavailable",
                        "Could not start or connect to Lock-In",
                    )
                ),
            )
        except OSError:
            pass
        return 1
    return NativeRelay(connection, sys.stdin.buffer, sys.stdout.buffer).run()


if __name__ == "__main__":
    raise SystemExit(main())
