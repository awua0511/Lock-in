from __future__ import annotations

from lock_in.context.aggregator import ContextResolution
from lock_in.context.application_service import BrowserContextApplicationService
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ResolutionStatus,
)


class FakeFocus:
    def __init__(self) -> None:
        self.foregrounds = []
        self.contexts = []

    def observe_foreground(self, observation) -> None:
        self.foregrounds.append(observation)

    def observe_website_context(self, context, **metadata) -> None:
        self.contexts.append((context, metadata))


def _foreground(at_ms: int = 100) -> ForegroundObservation:
    return ForegroundObservation(
        sequence=1,
        observed_at="2026-09-14T13:05:00+00:00",
        monotonic_ms=at_ms,
        hwnd=10,
        pid=100,
        application_name="chrome",
        executable_path=r"C:\Program Files\Chrome\chrome.exe",
        status=ResolutionStatus.IDENTIFIED,
    )


def test_foreground_requests_snapshot_and_correlated_response_resolves_context() -> (
    None
):
    focus = FakeFocus()
    sent = []
    service = BrowserContextApplicationService(
        focus,
        lambda connection_id, message: sent.append((connection_id, message)) or True,
    )
    service.browser_event(
        {
            "event": "connected",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
        },
        10,
    )
    service.foreground_observed(_foreground(), 100)

    assert sent[-1][0] == "connection-a"
    assert sent[-1][1]["type"] == "request_snapshot"
    request_id = sent[-1][1]["payload"]["snapshotRequestId"]
    epoch = sent[-1][1]["payload"]["foregroundEpoch"]
    service.browser_event(
        {
            "event": "browser_context_snapshot",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
            "sequence": 1,
            "payload": {
                "windowId": 1,
                "tabId": 2,
                "domain": "github.com",
                "windowFocused": True,
                "snapshotRequestId": request_id,
                "foregroundEpoch": epoch,
            },
        },
        120,
    )

    context = service.current_context
    assert context is not None
    assert context.resolution is ContextResolution.RESOLVED
    assert context.website_evaluation_allowed
    assert context.browser is not None and context.browser.domain == "github.com"
    assert focus.contexts[-1][0] == context


def test_unrequested_or_stale_context_never_becomes_evaluable() -> None:
    focus = FakeFocus()
    service = BrowserContextApplicationService(focus, lambda _id, _message: True)
    service.browser_event(
        {
            "event": "connected",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
        },
        10,
    )
    service.foreground_observed(_foreground(), 100)
    request = service.current_context
    assert request is not None

    service.browser_event(
        {
            "event": "browser_context_snapshot",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
            "sequence": 1,
            "payload": {
                "windowId": 1,
                "tabId": 2,
                "domain": "youtube.com",
                "windowFocused": True,
                "snapshotRequestId": "old-request",
                "foregroundEpoch": request.foreground_epoch - 1,
            },
        },
        120,
    )

    assert service.current_context is not None
    assert service.current_context.resolution is ContextResolution.PENDING
    assert service.current_context.browser is None


def test_unknown_proactive_context_requests_fresh_snapshot_for_recovery() -> None:
    focus = FakeFocus()
    sent = []
    service = BrowserContextApplicationService(
        focus,
        lambda connection_id, message: sent.append((connection_id, message)) or True,
    )
    service.browser_event(
        {
            "event": "connected",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
        },
        10,
    )
    service.foreground_observed(_foreground(), 100)
    initial_request = sent[-1][1]
    service.browser_event(
        {
            "event": "browser_context_snapshot",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
            "sequence": 1,
            "payload": {
                "windowId": 1,
                "tabId": 2,
                "domain": "github.com",
                "windowFocused": True,
                "snapshotRequestId": initial_request["payload"]["snapshotRequestId"],
                "foregroundEpoch": initial_request["payload"]["foregroundEpoch"],
            },
        },
        120,
    )
    service.browser_event(
        {
            "event": "browser_context_snapshot",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
            "sequence": 2,
            "payload": {
                "windowId": -1,
                "tabId": -1,
                "domain": None,
                "windowFocused": False,
                "snapshotRequestId": None,
                "foregroundEpoch": None,
            },
        },
        130,
    )
    service.browser_event(
        {
            "event": "browser_context_snapshot",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
            "sequence": 3,
            "payload": {
                "windowId": 1,
                "tabId": 3,
                "domain": "youtube.com",
                "windowFocused": True,
                "snapshotRequestId": None,
                "foregroundEpoch": None,
            },
        },
        140,
    )

    refresh_request = sent[-1][1]
    assert refresh_request["type"] == "request_snapshot"
    service.browser_event(
        {
            "event": "browser_context_snapshot",
            "connectionId": "connection-a",
            "clientInstanceId": "profile-a",
            "browser": "chrome",
            "sequence": 4,
            "payload": {
                "windowId": 1,
                "tabId": 3,
                "domain": "youtube.com",
                "windowFocused": True,
                "snapshotRequestId": refresh_request["payload"]["snapshotRequestId"],
                "foregroundEpoch": refresh_request["payload"]["foregroundEpoch"],
            },
        },
        150,
    )

    assert service.current_context is not None
    assert service.current_context.resolution == ContextResolution.RESOLVED
    assert service.current_context.browser is not None
    assert service.current_context.browser.domain == "youtube.com"


def test_connecting_profile_revalidates_without_replaying_old_foreground_time():
    focus = FakeFocus()
    sent = []
    service = BrowserContextApplicationService(
        focus, lambda _id, message: sent.append(message) or True
    )
    service.foreground_observed(_foreground(100), 100)
    service.browser_event(
        {
            "event": "connected",
            "connectionId": "late-connection",
            "clientInstanceId": "profile",
            "browser": "chrome",
        },
        60000,
    )
    assert len(focus.foregrounds) == 1
    assert service.current_context.received_monotonic_ms == 60000
    assert focus.contexts[-1][1]["monotonic_ms"] == 60000
    assert sent[-1]["type"] == "request_snapshot"
