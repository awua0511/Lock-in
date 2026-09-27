from __future__ import annotations

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
