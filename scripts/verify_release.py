"""Exercise real packaged processes using disposable data and isolated pipe names."""

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
from pathlib import Path

import psutil

from lock_in.communication.protocol import decode_message, encode_message
from lock_in.distribution.bundle import validate_bundle
from lock_in.native_host.main import read_native_message, write_native_message


def wait_started(process, log: Path, timeout=12, *, previous_starts=0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Packaged application exited early: {process.returncode}"
            )
        if (
            log.exists()
            and log.read_text(encoding="utf-8").count("application_started")
            > previous_starts
        ):
            return
        time.sleep(0.05)
    raise TimeoutError("Packaged application did not start")


def desktop_children(hosts, executable, namespace):
    result = {}
    for host in hosts:
        try:
            children = psutil.Process(host.process.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            continue
        for child in children:
            try:
                if (
                    Path(child.exe()).resolve() == executable.resolve()
                    and namespace in child.cmdline()
                ):
                    result[child.pid] = child
            except psutil.NoSuchProcess:
                continue
    return result


class Host:
    def __init__(self, executable, environment, browser="chrome", profile="one"):
        self.process = subprocess.Popen(
            [str(executable)],
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.messages = queue.Queue()
        self.browser, self.profile = browser, profile
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.send("hello", 0)
            assert self.receive()["type"] == "hello_ack"
        except BaseException:
            for child in psutil.Process(self.process.pid).children(recursive=True):
                if (
                    Path(child.exe()).resolve()
                    == Path(executable).resolve().parent / "lock-in.exe"
                ):
                    child.terminate()
                    child.wait(5)
            self.close()
            raise

    def _read(self):
        try:
            while body := read_native_message(self.process.stdout):
                self.messages.put(decode_message(body))
        except (OSError, ValueError):
            pass

    def send(self, kind, sequence):
        write_native_message(
            self.process.stdin,
            encode_message(
                {
                    "protocolVersion": 1,
                    "messageId": str(uuid.uuid4()),
                    "type": kind,
                    "clientInstanceId": self.profile,
                    "browser": self.browser,
                    "sequence": sequence,
                    "payload": {},
                }
            ),
        )

    def receive(self):
        return self.messages.get(timeout=12)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def environment(root, namespace):
    return {
        **os.environ,
        "LOCALAPPDATA": str(root),
        "LOCK_IN_NAMESPACE": namespace,
        "QT_QPA_PLATFORM": "offscreen",
    }


def exercise(bundle: Path, output: Path, seconds: int) -> dict:
    print(
        "Checking bundle integrity and packaged startup...", file=sys.stderr, flush=True
    )
    validate_bundle(bundle)
    output.mkdir(parents=True, exist_ok=False)
    desktop = bundle / "lock-in.exe"
    host_executable = bundle / "lock-in-production-native-host.exe"
    namespace = "release-" + uuid.uuid4().hex
    env = environment(output / "profile", namespace)
    diagnostics = output / "diagnostics.json"
    data = output / "profile/LockIn"
    command = [
        str(desktop),
        "--instance-namespace",
        namespace,
        "--data-directory",
        str(data),
        "--log-directory",
        str(data / "Logs"),
        "--no-tray",
        "--smoke-test-duration",
        str(seconds + 10),
        "--diagnostics-file",
        str(diagnostics),
    ]
    started = time.monotonic()
    process = subprocess.Popen(
        command, env=env, creationflags=subprocess.CREATE_NO_WINDOW
    )
    hosts = []
    try:
        wait_started(process, data / "Logs/lock-in.log")
        startup = (time.monotonic() - started) * 1000
        duplicate = subprocess.run(
            command, env=env, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW
        )
        assert duplicate.returncode == 0 and process.poll() is None
        for browser, profile in (
            ("chrome", "chrome-a"),
            ("chrome", "chrome-b"),
            ("edge", "edge-a"),
        ):
            hosts.append(Host(host_executable, env, browser, profile))
        for seq, expected in ((10, "accepted"), (10, "duplicate"), (9, "out_of_order")):
            hosts[0].send("browser_context_snapshot", seq)
            assert hosts[0].receive()["status"] == expected
        hosts[0].close()
        hosts[0] = Host(host_executable, env, "chrome", "chrome-a")
        roundtrips = []
        for sequence in range(30):
            before = time.monotonic()
            hosts[1].send("heartbeat", sequence)
            assert hosts[1].receive()["type"] == "heartbeat_ack"
            roundtrips.append((time.monotonic() - before) * 1000)
        measured = psutil.Process(process.pid)
        print(
            f"Sampling packaged GUI performance for {seconds} seconds...",
            file=sys.stderr,
            flush=True,
        )
        initial = measured.cpu_times()
        wall = time.monotonic()
        memory = []
        for _ in range(seconds * 2):
            memory.append(measured.memory_info().rss / 1024**2)
            time.sleep(0.5)
        final = measured.cpu_times()
        cpu = (
            100
            * ((final.user + final.system) - (initial.user + initial.system))
            / (time.monotonic() - wall)
        )
        assert process.wait(timeout=12) == 0
        results = {
            "startup_to_ready_ms": round(startup, 2),
            "idle_single_core_cpu_percent": round(cpu, 3),
            "working_set_peak_mib": round(max(memory), 2),
            "idle_sample_seconds": seconds,
            "native_message_roundtrip_p95_ms": round(sorted(roundtrips)[28], 3),
            "native_message_roundtrip_samples": len(roundtrips),
            **json.loads(diagnostics.read_text()),
        }
    finally:
        for host in hosts:
            host.close()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)

    # Corrupt data must be reported and preserved, not silently reset.
    print(
        "Checking recovery and concurrent Host startup...", file=sys.stderr, flush=True
    )
    corrupt = output / "corrupt"
    corrupt.mkdir()
    database = corrupt / "lock-in.sqlite3"
    database.write_bytes(b"intentional corrupted test database")
    broken = subprocess.run(
        [
            str(desktop),
            "--instance-namespace",
            namespace + "-bad",
            "--data-directory",
            str(corrupt),
            "--log-directory",
            str(corrupt),
            "--no-tray",
            "--smoke-test-duration",
            "1.2",
        ],
        env=env,
        timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert broken.returncode == 0
    assert database.read_bytes() == b"intentional corrupted test database"
    assert "component_failed" in (corrupt / "lock-in.log").read_text(encoding="utf-8")
    results["corrupt_database_preserved"] = True

    # Two packaged Hosts launch the missing packaged desktop concurrently.
    # This is isolated from the user's exit marker, database and default mutex.
    auto_namespace = namespace + "-auto"
    auto_env = environment(output / "auto-profile", auto_namespace)
    auto_hosts = []
    launched = {}
    errors = queue.Queue()

    def launch(browser):
        try:
            auto_hosts.append(Host(host_executable, auto_env, browser, browser))
        except Exception as error:
            errors.put(error)

    threads = [
        threading.Thread(target=launch, args=(browser,), daemon=True)
        for browser in ("chrome", "edge")
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        assert not any(t.is_alive() for t in threads)
        if not errors.empty():
            raise errors.get()
        assert len(auto_hosts) == 2
        # A rejected duplicate may still be tearing down its frozen runtime
        # when the winner starts accepting messages. Require a settled result.
        deadline = time.monotonic() + 5
        stable_since = None
        while time.monotonic() < deadline:
            active = desktop_children(auto_hosts, desktop, auto_namespace)
            launched.update(active)
            if len(active) == 1:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= 0.5:
                    break
            else:
                stable_since = None
            time.sleep(0.05)
        assert stable_since is not None and len(active) == 1, (
            f"concurrent Host startup left desktop PIDs: {list(active)}"
        )
        auto_log = output / "auto-profile/LockIn/Logs/lock-in.log"
        assert auto_log.read_text(encoding="utf-8").count("application_started") == 1
        results["simultaneous_packaged_host_autostart"] = True
    finally:
        launched.update(desktop_children(auto_hosts, desktop, auto_namespace))
        for child in launched.values():
            try:
                child.terminate()
                child.wait(5)
            except psutil.NoSuchProcess:
                pass
        for host in auto_hosts:
            host.close()

    # Restart on the same isolated profile/pipe and reconnect a fresh Host.
    log = data / "Logs/lock-in.log"
    previous_starts = log.read_text(encoding="utf-8").count("application_started")
    restarted = subprocess.Popen(
        [*command[:-2], "--diagnostics-file", str(output / "restart-diagnostics.json")],
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    fresh = None
    try:
        wait_started(restarted, log, previous_starts=previous_starts)
        fresh = Host(host_executable, env, "edge", "reloaded-profile")
        fresh.send("heartbeat", 20)
        assert fresh.receive()["type"] == "heartbeat_ack"
    finally:
        if fresh is not None:
            fresh.close()
        if restarted.poll() is None:
            restarted.terminate()
        restarted.wait(5)
    results["installer"] = exercise_installer(bundle, output / "installer-profile")
    results["checks"] = [
        "bundle_integrity",
        "packaged_gui_start_shutdown",
        "single_instance",
        "chrome_edge_multiple_profiles",
        "ordering_and_duplicates",
        "host_crash_reconnect",
        "desktop_restart_extension_reconnect",
        "simultaneous_host_autostart",
        "corrupt_database_fail_open",
        "packaged_setup_install_upgrade_rollback_uninstall",
    ]
    results["budgets"] = {
        "startup_under_5s": startup < 5000,
        "idle_cpu_under_2_percent_single_core": cpu < 2,
        "working_set_under_250_mib": max(memory) < 250,
        "queue_p95_under_250ms": results["queue_latency_p95_ms"] < 250,
    }
    (output / "results.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    assert all(results["budgets"].values()), results
    return results


def exercise_installer(bundle: Path, profile: Path) -> dict:
    """Run the real CLI without browser IDs, so no browser registration is changed."""
    from lock_in.distribution.installer import UserRegistry

    profile.mkdir()
    preserved = profile / "LockIn/keep-user-data.txt"
    preserved.parent.mkdir()
    preserved.write_bytes(b"user data must remain")
    root = profile / "Programs/LockIn"
    registry = UserRegistry()
    before = {browser: registry.read(browser) for browser in ("chrome", "edge")}
    env = environment(profile, "installer-" + uuid.uuid4().hex)
    setup = bundle / "lock-in-setup.exe"

    def run(action):
        print(
            f"Checking packaged setup: {action} (isolated data)...",
            file=sys.stderr,
            flush=True,
        )
        completed = subprocess.run(
            [str(setup), action],
            env=env,
            capture_output=True,
            timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")

    def state():
        return json.loads((root / "installation.json").read_text(encoding="utf-8"))

    run("install")
    first = state()
    run("install")
    assert state()["previous"] == first["current"]
    assert (root / "Start Lock-In.cmd").is_file()
    assert (root / "extension/manifest.json").is_file()
    run("rollback")
    assert state()["current"] == first["current"]
    run("uninstall")
    assert not root.exists()
    assert preserved.read_bytes() == b"user data must remain"
    assert before == {browser: registry.read(browser) for browser in before}
    return {
        "lifecycle_passed": True,
        "user_data_and_browser_registration_unchanged": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    if args.seconds < 5:
        parser.error("Use at least five seconds of idle sampling")
    print(
        json.dumps(
            exercise(args.bundle.resolve(), args.output.resolve(), args.seconds),
            indent=2,
        )
    )
