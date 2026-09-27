from lock_in.platform.windows.system_events import (
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMSUSPEND,
    WM_POWERBROADCAST,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    WTS_SESSION_UNLOCK,
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
