from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows application test")


def _command(namespace: str, log_directory: Path, duration: float) -> list[str]:
    return [
        sys.executable,
        "-m",
        "lock_in.app.main",
        "--instance-namespace",
        namespace,
        "--log-directory",
        str(log_directory),
        "--data-directory",
        str(log_directory),
        "--no-tray",
        "--smoke-test-duration",
        str(duration),
    ]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    return environment


def _wait_until_started(process: subprocess.Popen[str], log_path: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _, stderr = process.communicate()
            pytest.fail(f"first instance exited before readiness: {stderr}")
        if log_path.exists() and "application_started" in log_path.read_text(
            encoding="utf-8"
        ):
            return
        time.sleep(0.05)
    pytest.fail("first instance did not report readiness within five seconds")


def test_single_instance_rejects_duplicate_and_releases_mutex(
    tmp_path: Path,
) -> None:
    namespace = f"test-{uuid.uuid4()}"
    first = subprocess.Popen(
        _command(namespace, tmp_path, 1.5),
        env=_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_until_started(first, tmp_path / "lock-in.log")
        duplicate = subprocess.run(
            _command(namespace, tmp_path, 0.2),
            env=_environment(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert duplicate.returncode == 0, duplicate.stderr
        assert first.poll() is None
        assert first.wait(timeout=5) == 0

        restarted = subprocess.run(
            _command(namespace, tmp_path, 0.1),
            env=_environment(),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert restarted.returncode == 0, restarted.stderr
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=5)

    log = (tmp_path / "lock-in.log").read_text(encoding="utf-8")
    assert "duplicate_start_rejected" in log
    assert log.count("application_started") == 2
    connection = sqlite3.connect(tmp_path / "lock-in.sqlite3")
    try:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,)]
    finally:
        connection.close()
