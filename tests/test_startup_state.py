from __future__ import annotations

import pytest

from lock_in.app import config


def test_user_exit_marker_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert not config.user_requested_exit()
    config.mark_user_requested_exit()
    assert config.user_requested_exit()
    assert config.user_exit_marker_path().is_file()

    config.clear_user_requested_exit()
    assert not config.user_requested_exit()


def test_native_host_does_not_relaunch_after_explicit_exit(monkeypatch) -> None:
    from lock_in.native_host import main as host_main

    monkeypatch.setattr(host_main, "user_requested_exit", lambda: True)

    try:
        host_main.connect_or_launch("default", production=True)
    except ConnectionError as error:
        assert "explicitly closed" in str(error)
    else:
        raise AssertionError("production host should respect an explicit exit")


def test_delayed_host_launch_cannot_clear_explicit_exit_marker(tmp_path, monkeypatch):
    from lock_in.app import main as application

    class Mutex:
        already_exists = False

        def close(self):
            pass

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config.mark_user_requested_exit()
    monkeypatch.setattr(application, "SingleInstanceMutex", lambda _name: Mutex())
    monkeypatch.setattr(application, "application_mutex_name", lambda _name: "test")
    calls = []
    monkeypatch.setattr(
        application, "_run_application", lambda _args, _log: calls.append("run") or 0
    )
    assert application.main(["--host-launched"]) == 0
    assert config.user_requested_exit()
    assert calls == []
    assert application.main([]) == 0
    assert not config.user_requested_exit()
    assert calls == ["run"]


def test_damaged_frozen_bundle_never_launches_the_host_as_python(tmp_path, monkeypatch):
    from lock_in.native_host import main as host

    monkeypatch.setattr(host.sys, "frozen", True, raising=False)
    monkeypatch.setattr(host.sys, "executable", str(tmp_path / "host.exe"))
    with pytest.raises(FileNotFoundError, match="desktop executable"):
        host._launch_application("test")
