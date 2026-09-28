from lock_in.platform.windows.system_events import (
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMSUSPEND,
    WM_ENDSESSION,
    WM_POWERBROADCAST,
    WM_QUERYENDSESSION,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
    SystemAvailability,
    decode_system_message,
)


def test_decodes_lock_sleep_and_resume_without_windows() -> None:
    assert decode_system_message(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK) == (
        False,
        "session_lock",
    )
    assert decode_system_message(WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK) == (
        True,
        "session_unlock",
    )
    assert decode_system_message(WM_POWERBROADCAST, PBT_APMSUSPEND) == (
        False,
        "system_suspend",
    )
    assert decode_system_message(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC) == (
        True,
        "system_resume",
    )
    assert decode_system_message(0, 0) is None


def test_resume_does_not_unlock_a_locked_session():
    state = SystemAvailability()
    assert state.consume(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK)[0] is False
    assert state.consume(WM_POWERBROADCAST, PBT_APMSUSPEND) is None
    assert state.consume(WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC) is None
    assert not state.available
    assert state.consume(WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK)[0] is True


def test_cancelled_shutdown_restores_availability():
    state = SystemAvailability()
    assert state.consume(WM_QUERYENDSESSION, 0)[0] is False
    assert state.consume(WM_ENDSESSION, 0)[0] is True
