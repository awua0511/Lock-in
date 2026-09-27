from __future__ import annotations

from datetime import UTC, datetime, time

from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
    Recurrence,
    RecurrenceKind,
    Schedule,
    TargetType,
    WebsiteAllowlistEntry,
)
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)
from lock_in.rules.application_policy import (
    ApplicationFocusPolicy,
    FocusConfiguration,
    PolicyDecision,
)


def _schedule() -> Schedule:
    return Schedule(
        id="focus",
        name="Focus",
        start_time=time(13),
        end_time=time(14),
        timezone="UTC",
        recurrences=(Recurrence(kind=RecurrenceKind.WEEKLY, weekday=0),),
    )


def _observe(policy: ApplicationFocusPolicy, domain: str):
    return policy.observe_website(
        context_id=f"context-{domain}",
        foreground_epoch=1,
        revision=1,
        hwnd=20,
        pid=200,
        browser_name="Chrome",
        executable_path=r"C:\Program Files\Chrome\chrome.exe",
        domain=domain,
        now=datetime(2026, 9, 14, 13, 5, tzinfo=UTC),
    )


def test_exact_and_subdomain_rules_are_label_bounded() -> None:
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(
        FocusConfiguration(
            (_schedule(),),
            (),
            websites=(WebsiteAllowlistEntry("example.com"),),
        )
    )

    assert _observe(policy, "example.com").prompt is None
    assert _observe(policy, "docs.example.com").prompt is None
    evil = _observe(policy, "example.com.evil.test").prompt
    assert evil is not None
    assert evil.target_type is TargetType.WEBSITE
    assert evil.target_key == "example.com.evil.test"


def test_exact_host_rule_can_disable_subdomains_and_continue_is_entry_scoped() -> None:
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(
        FocusConfiguration(
            (_schedule(),),
            (),
            websites=(WebsiteAllowlistEntry("example.com", include_subdomains=False),),
        )
    )

    assert _observe(policy, "example.com").prompt is None
    prompt = _observe(policy, "docs.example.com").prompt
    assert prompt is not None
    policy.decide(prompt.id, PolicyDecision.CONTINUE)
    assert _observe(policy, "docs.example.com").prompt is None
    assert _observe(policy, "other.example.com").prompt is not None


def test_repeated_update_for_same_website_keeps_prompt_decidable() -> None:
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(FocusConfiguration((_schedule(),), ()))
    first = _observe(policy, "youtube.com").prompt
    assert first is not None

    repeated = policy.observe_website(
        context_id="context-2",
        foreground_epoch=1,
        revision=2,
        hwnd=20,
        pid=200,
        browser_name="Chrome",
        executable_path=r"C:\Program Files\Chrome\chrome.exe",
        domain="youtube.com",
        now=datetime(2026, 9, 14, 13, 5, tzinfo=UTC),
    )

    assert repeated.prompt is None
    assert not repeated.dismiss_prompt
    assert policy.active_prompt == first
    result = policy.decide(first.id, PolicyDecision.CONTINUE)
    assert result is not None
    assert result.decision is PolicyDecision.CONTINUE


def test_browser_pending_transition_preserves_continue_for_same_site_only() -> None:
    policy = ApplicationFocusPolicy(own_pid=999)
    policy.update_configuration(FocusConfiguration((_schedule(),), ()))
    prompt = _observe(policy, "youtube.com").prompt
    assert prompt is not None
    policy.decide(prompt.id, PolicyDecision.CONTINUE)

    policy.invalidate_website_context(preserve_continued=True)
    same_site = policy.observe_website(
        context_id="new-foreground-epoch",
        foreground_epoch=2,
        revision=1,
        hwnd=20,
        pid=200,
        browser_name="Chrome",
        executable_path=r"C:\Program Files\Chrome\chrome.exe",
        domain="youtube.com",
        now=datetime(2026, 9, 14, 13, 5, tzinfo=UTC),
    )
    other_site = policy.observe_website(
        context_id="new-foreground-epoch",
        foreground_epoch=2,
        revision=2,
        hwnd=20,
        pid=200,
        browser_name="Chrome",
        executable_path=r"C:\Program Files\Chrome\chrome.exe",
        domain="reddit.com",
        now=datetime(2026, 9, 14, 13, 5, tzinfo=UTC),
    )

    assert same_site.prompt is None
    assert other_site.prompt is not None


def test_website_return_targets_last_non_browser_allowed_window() -> None:
    policy = ApplicationFocusPolicy(own_pid=999)
    allowed_window = ApplicationAllowlistEntry(
        identity=ApplicationIdentity(
            kind=ApplicationKind.WIN32,
            display_name="Word",
            executable_path=r"C:\Work\Word.exe",
        )
    )
    policy.update_configuration(FocusConfiguration((_schedule(),), (allowed_window,)))
    now = datetime(2026, 9, 14, 13, 5, tzinfo=UTC)

    def observe_foreground(sequence: int, hwnd: int, path: str) -> None:
        policy.observe(
            ForegroundObservation(
                sequence=sequence,
                observed_at=now.isoformat(),
                monotonic_ms=sequence,
                hwnd=hwnd,
                pid=sequence + 100,
                application_name=path.rsplit("\\", 1)[-1],
                executable_path=path,
                status=ResolutionStatus.IDENTIFIED,
            ),
            now,
        )

    observe_foreground(1, 10, r"C:\Work\Word.exe")
    observe_foreground(2, 20, r"C:\Program Files\Chrome\chrome.exe")
    prompt = _observe(policy, "youtube.com").prompt

    assert prompt is not None
    assert prompt.return_hwnd == 10
    result = policy.decide(prompt.id, PolicyDecision.RETURN)
    assert result is not None
    assert result.activate_hwnd == 10
