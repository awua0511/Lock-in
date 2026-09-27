from __future__ import annotations

import pytest

from lock_in.sessions.foreground_timer import ContinuedUseTimer

TARGET = (20, r"c:\games\steam.exe")


def test_counts_only_while_continued_target_is_foreground() -> None:
    timer = ContinuedUseTimer(30)
    timer.arm(TARGET)
    timer.observe(TARGET, 1_000)
    assert timer.tick(20_000) is None

    segment = timer.observe((10, r"c:\work\word.exe"), 21_000)

    assert segment is not None and segment.duration_ms == 20_000
    assert timer.target_key is None
    assert timer.tick(60_000) is None


def test_suspend_excludes_sleep_and_requires_fresh_foreground_event() -> None:
    timer = ContinuedUseTimer(30)
    timer.arm(TARGET)
    timer.observe(TARGET, 1_000)
    first = timer.suspend(11_000)
    timer.resume()

    assert first is not None and first.duration_ms == 10_000
    assert timer.tick(100_000) is None

    timer.observe(TARGET, 100_000)
    due = timer.tick(120_000)
    assert due is not None and due.foreground_ms == 30_000


def test_wall_clock_is_absent_and_monotonic_regression_is_rejected() -> None:
    timer = ContinuedUseTimer(30)
    timer.arm(TARGET)
    timer.observe(TARGET, 50_000)

    with pytest.raises(ValueError, match="moved backwards"):
        timer.tick(49_999)


def test_continue_after_follow_up_starts_a_new_threshold() -> None:
    timer = ContinuedUseTimer(30)
    timer.arm(TARGET)
    timer.observe(TARGET, 0)
    assert timer.tick(30_000) is not None

    timer.arm(TARGET)
    timer.observe(TARGET, 31_000)
    assert timer.tick(60_999) is None
    assert timer.tick(61_000) is not None
