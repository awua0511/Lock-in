from __future__ import annotations

from lock_in.context.aggregator import (
    ApplicationIdentity,
    BrowserClient,
    BrowserSnapshot,
    ContextAggregator,
    ContextResolution,
    EventDisposition,
)


CHROME = ApplicationIdentity(
    executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    browser_kind="chrome",
)
WORD = ApplicationIdentity(
    executable_path=r"C:\Program Files\Microsoft Office\WINWORD.EXE",
)
CLIENT_A = BrowserClient("connection-a", "profile-a", "chrome")


def snapshot(
    at_ms: int,
    sequence: int,
    domain: str | None,
    *,
    connection_id: str = "connection-a",
    client_id: str = "profile-a",
    request_id: str | None = "snapshot-1",
    epoch: int | None = 1,
    focused: bool = True,
) -> BrowserSnapshot:
    return BrowserSnapshot(
        received_ms=at_ms,
        connection_id=connection_id,
        client_instance_id=client_id,
        browser_kind="chrome",
        sequence=sequence,
        window_id=1,
        tab_id=sequence,
        domain=domain,
        window_focused=focused,
        snapshot_request_id=request_id,
        requested_foreground_epoch=epoch,
    )


def test_required_timeline_rejects_old_and_late_domains() -> None:
    aggregator = ContextAggregator()
    aggregator.connect_client(CLIENT_A)

    entered = aggregator.foreground_changed(received_ms=0, application=CHROME)
    old = aggregator.browser_snapshot(
        snapshot(20, 40, "youtube.com", request_id="snapshot-previous", epoch=0)
    )
    current = aggregator.browser_snapshot(snapshot(80, 41, "github.com"))
    word = aggregator.foreground_changed(received_ms=90, application=WORD)
    late = aggregator.browser_snapshot(snapshot(110, 42, "youtube.com"))

    assert entered.context is not None
    assert entered.context.resolution == ContextResolution.PENDING
    assert entered.context.browser is None
    assert old.disposition == EventDisposition.REJECTED
    assert old.reason == "stale_snapshot_request"
    assert old.context_changed is False
    assert current.context is not None
    assert current.context.browser is not None
    assert current.context.browser.domain == "github.com"
    assert word.context is not None
    assert word.context.application == WORD
    assert word.context.browser is None
    assert word.context.website_evaluation_allowed is False
    assert late.disposition == EventDisposition.REJECTED
    assert late.reason == "no_browser_foreground"
    assert late.context_changed is False
    assert late.context == word.context


def test_duplicate_snapshot_is_processed_only_once() -> None:
    aggregator = ContextAggregator()
    aggregator.connect_client(CLIENT_A)
    aggregator.foreground_changed(received_ms=0, application=CHROME)
    first_message = snapshot(50, 1, "github.com")

    first = aggregator.browser_snapshot(first_message)
    duplicate = aggregator.browser_snapshot(first_message)

    assert first.context_changed is True
    assert duplicate.disposition == EventDisposition.DUPLICATE
    assert duplicate.context_changed is False
    assert duplicate.context == first.context


def test_timeout_outputs_unknown_without_reusing_previous_domain() -> None:
    aggregator = ContextAggregator(snapshot_wait_ms=300)
    aggregator.connect_client(CLIENT_A)
    aggregator.foreground_changed(received_ms=0, application=CHROME)
    resolved = aggregator.browser_snapshot(snapshot(20, 1, "github.com"))
    assert resolved.context is not None and resolved.context.browser is not None

    aggregator.foreground_changed(received_ms=30, application=WORD)
    pending = aggregator.foreground_changed(received_ms=40, application=CHROME)
    timed_out = aggregator.advance_time(340)

    assert pending.context is not None
    assert pending.context.resolution == ContextResolution.PENDING
    assert pending.context.browser is None
    assert timed_out.context is not None
    assert timed_out.context.resolution == ContextResolution.UNKNOWN
    assert timed_out.context.browser is None
    assert timed_out.context.website_evaluation_allowed is False


def test_two_focused_profiles_are_ambiguous_and_become_unknown() -> None:
    aggregator = ContextAggregator()
    aggregator.connect_client(CLIENT_A)
    aggregator.connect_client(BrowserClient("connection-b", "profile-b", "chrome"))
    entered = aggregator.foreground_changed(received_ms=0, application=CHROME)
    assert entered.snapshot_request is not None

    first = aggregator.browser_snapshot(snapshot(20, 1, "github.com"))
    second = aggregator.browser_snapshot(
        snapshot(
            30,
            1,
            "youtube.com",
            connection_id="connection-b",
            client_id="profile-b",
        )
    )

    assert first.context_changed is False
    assert first.context is not None
    assert first.context.resolution == ContextResolution.PENDING
    assert second.context is not None
    assert second.context.resolution == ContextResolution.UNKNOWN
    assert second.context.browser is None


def test_missing_profile_response_is_unknown_at_timeout() -> None:
    aggregator = ContextAggregator(snapshot_wait_ms=100)
    aggregator.connect_client(CLIENT_A)
    aggregator.connect_client(BrowserClient("connection-b", "profile-b", "chrome"))
    aggregator.foreground_changed(received_ms=0, application=CHROME)
    aggregator.browser_snapshot(snapshot(20, 1, "github.com"))

    result = aggregator.advance_time(100)

    assert result.context is not None
    assert result.context.resolution == ContextResolution.UNKNOWN
    assert result.context.browser is None


def test_proactive_snapshot_updates_only_bound_profile() -> None:
    aggregator = ContextAggregator()
    aggregator.connect_client(CLIENT_A)
    aggregator.foreground_changed(received_ms=0, application=CHROME)
    resolved = aggregator.browser_snapshot(snapshot(20, 1, "github.com"))
    proactive = aggregator.browser_snapshot(
        snapshot(40, 2, "docs.python.org", request_id=None, epoch=None)
    )

    assert resolved.context is not None
    assert proactive.context is not None
    assert proactive.context.browser is not None
    assert proactive.context.browser.domain == "docs.python.org"
    assert proactive.context.context_revision == resolved.context.context_revision + 1


def test_out_of_order_snapshot_cannot_change_context() -> None:
    aggregator = ContextAggregator()
    aggregator.connect_client(CLIENT_A)
    aggregator.foreground_changed(received_ms=0, application=CHROME)
    resolved = aggregator.browser_snapshot(snapshot(20, 5, "github.com"))

    old = aggregator.browser_snapshot(
        snapshot(30, 4, "youtube.com", request_id=None, epoch=None)
    )

    assert old.disposition == EventDisposition.OUT_OF_ORDER
    assert old.context_changed is False
    assert old.context == resolved.context


def test_new_browser_epoch_starts_pending_without_previous_domain() -> None:
    aggregator = ContextAggregator()
    aggregator.connect_client(CLIENT_A)
    aggregator.foreground_changed(received_ms=0, application=CHROME)
    aggregator.browser_snapshot(snapshot(20, 1, "github.com"))
    aggregator.foreground_changed(received_ms=30, application=WORD)

    new_epoch = aggregator.foreground_changed(received_ms=40, application=CHROME)

    assert new_epoch.context is not None
    assert new_epoch.context.foreground_epoch == 3
    assert new_epoch.context.resolution == ContextResolution.PENDING
    assert new_epoch.context.browser is None
    assert new_epoch.context.website_evaluation_allowed is False
