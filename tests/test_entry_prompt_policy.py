from __future__ import annotations

from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)
from lock_in.prompts.entry_policy import EntryPromptPolicy, PromptDecision


def observation(
    hwnd: int,
    path: str,
    *,
    pid: int = 42,
    status: ResolutionStatus = ResolutionStatus.IDENTIFIED,
) -> ForegroundObservation:
    return ForegroundObservation(
        sequence=1,
        observed_at="2026-09-17T10:00:00.000-04:00",
        monotonic_ms=100,
        hwnd=hwnd,
        pid=pid,
        application_name=path.rsplit("\\", 1)[-1].removesuffix(".exe"),
        executable_path=path,
        status=status,
    )


ALLOWED = r"C:\Work\Editor.exe"
DISTRACTION = r"C:\Games\Game.exe"


def test_allowed_application_does_not_prompt_and_becomes_return_target() -> None:
    policy = EntryPromptPolicy([ALLOWED], own_pid=999)

    result = policy.observe(observation(100, ALLOWED))

    assert result is None
    assert policy.last_allowed_hwnd == 100


def test_disallowed_entry_prompts_with_previous_allowed_window() -> None:
    policy = EntryPromptPolicy([ALLOWED], own_pid=999)
    policy.observe(observation(100, ALLOWED))

    request = policy.observe(observation(200, DISTRACTION))

    assert request is not None
    assert request.target_hwnd == 200
    assert request.return_hwnd == 100


def test_duplicate_event_does_not_create_duplicate_prompt() -> None:
    policy = EntryPromptPolicy([], own_pid=999)

    first = policy.observe(observation(200, DISTRACTION))
    duplicate = policy.observe(observation(200, DISTRACTION))

    assert first is not None
    assert duplicate is None


def test_continue_reactivation_does_not_immediately_reprompt() -> None:
    policy = EntryPromptPolicy([ALLOWED], own_pid=999)
    policy.observe(observation(100, ALLOWED))
    policy.observe(observation(200, DISTRACTION))

    result = policy.decide(PromptDecision.CONTINUE)
    reactivation = policy.observe(observation(200, DISTRACTION))

    assert result is not None
    assert result.activate_hwnd == 200
    assert reactivation is None


def test_leaving_and_reentering_after_continue_prompts_again() -> None:
    policy = EntryPromptPolicy([ALLOWED], own_pid=999)
    policy.observe(observation(100, ALLOWED))
    policy.observe(observation(200, DISTRACTION))
    policy.decide(PromptDecision.CONTINUE)
    policy.observe(observation(100, ALLOWED))

    request = policy.observe(observation(200, DISTRACTION))

    assert request is not None


def test_switching_between_disallowed_apps_ends_continue_suppression() -> None:
    policy = EntryPromptPolicy([], own_pid=999)
    policy.observe(observation(200, DISTRACTION))
    policy.decide(PromptDecision.CONTINUE)
    policy.observe(observation(300, r"C:\Social\Chat.exe"))

    request = policy.observe(observation(200, DISTRACTION))

    assert request is not None


def test_return_activates_previous_allowed_window() -> None:
    policy = EntryPromptPolicy([ALLOWED], own_pid=999)
    policy.observe(observation(100, ALLOWED))
    policy.observe(observation(200, DISTRACTION))

    result = policy.decide(PromptDecision.RETURN)

    assert result is not None
    assert result.activate_hwnd == 100


def test_own_process_and_unresolved_observations_are_ignored() -> None:
    policy = EntryPromptPolicy([], own_pid=42)

    own = policy.observe(observation(300, DISTRACTION, pid=42))
    unresolved = policy.observe(
        observation(
            400,
            DISTRACTION,
            pid=43,
            status=ResolutionStatus.PROCESS_ACCESS_DENIED,
        )
    )

    assert own is None
    assert unresolved is None


def test_path_comparison_is_case_insensitive_and_normalized() -> None:
    policy = EntryPromptPolicy([r"C:\Work\Editor.exe"], own_pid=999)

    result = policy.observe(observation(100, r"c:\work\folder\..\EDITOR.EXE"))

    assert result is None


def test_allowed_switch_cancels_a_stale_prompt() -> None:
    policy = EntryPromptPolicy([ALLOWED], own_pid=999)
    policy.observe(observation(200, DISTRACTION))

    result = policy.observe(observation(100, ALLOWED))

    assert result is None
    assert policy.active_prompt is None
