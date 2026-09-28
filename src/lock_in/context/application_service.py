"""Serialize foreground/browser aggregation and issue correlated snapshots."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

from lock_in.app.focus_service import FocusApplicationService
from lock_in.context.aggregator import (
    ApplicationIdentity,
    BrowserClient,
    BrowserSnapshot,
    ContextAggregator,
    ForegroundContext,
)
from lock_in.domain.models import normalize_domain
from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
)


class BrowserContextApplicationService:
    """Application-thread owner of ContextAggregator state."""

    def __init__(
        self,
        focus: FocusApplicationService,
        send: Callable[[str, dict[str, Any]], bool],
        health_sink: Callable[[str], None] | None = None,
        *,
        own_pid: int | None = None,
    ) -> None:
        self._focus = focus
        self._send = send
        self._health_sink = health_sink or (lambda _message: None)
        self._aggregator = ContextAggregator(snapshot_wait_ms=300)
        self._foreground: ForegroundObservation | None = None
        self._connections: dict[str, str] = {}
        self._own_pid = os.getpid() if own_pid is None else own_pid
        self._own_foreground = False
        self._available = True
        self._event_ms = 0

    @property
    def current_context(self) -> ForegroundContext | None:
        return self._aggregator.current_context

    def foreground_observed(
        self, observation: ForegroundObservation, monotonic_ms: int
    ) -> None:
        self._event_ms = monotonic_ms
        self._own_foreground = observation.pid == self._own_pid
        if self._own_foreground or not self._available:
            # Record/pause own-window use without destroying the decision whose
            # dialog just took focus. Browser messages cannot act behind it.
            self._focus.observe_foreground(observation)
            return
        self._foreground = observation
        browser_kind = _browser_kind(observation.executable_path)
        executable_path = observation.executable_path or ""
        result = self._aggregator.foreground_changed(
            received_ms=monotonic_ms,
            application=ApplicationIdentity(executable_path, browser_kind),
        )
        self._focus.observe_foreground(observation)
        if result.snapshot_request is not None:
            self._send_snapshot_requests(result.snapshot_request)
        if browser_kind is not None:
            self._focus.observe_website_context(
                result.context,
                hwnd=observation.hwnd or 0,
                pid=observation.pid or 0,
                executable_path=executable_path,
                browser_name=observation.application_name or browser_kind.title(),
                monotonic_ms=monotonic_ms,
            )
        else:
            self._focus.observe_website_context(
                None,
                hwnd=observation.hwnd or 0,
                pid=observation.pid or 0,
                executable_path=executable_path,
                browser_name="",
                monotonic_ms=monotonic_ms,
            )

    def browser_event(self, event: dict[str, Any], monotonic_ms: int) -> None:
        self._event_ms = monotonic_ms
        kind = event.get("event")
        connection_id = event.get("connectionId")
        if not isinstance(connection_id, str):
            return
        if kind == "connected":
            client_id = event.get("clientInstanceId")
            browser = event.get("browser")
            if isinstance(client_id, str) and isinstance(browser, str):
                self._connections[connection_id] = browser
                self._aggregator.connect_client(
                    BrowserClient(connection_id, client_id, browser)
                )
                self._publish_health()
                self._repeat_snapshot_request(browser)
            return
        if kind == "disconnected":
            result = self._aggregator.disconnect_client(
                connection_id, received_ms=monotonic_ms
            )
            self._connections.pop(connection_id, None)
            self._publish_health()
            if result.context_changed:
                self._apply_context(result.context)
            return
        if kind != "browser_context_snapshot":
            return
        if self._own_foreground or not self._available:
            return
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        client_id = event.get("clientInstanceId")
        browser = event.get("browser")
        sequence = event.get("sequence")
        window_id = payload.get("windowId")
        tab_id = payload.get("tabId")
        domain = payload.get("domain")
        focused = payload.get("windowFocused")
        request_id = payload.get("snapshotRequestId")
        epoch = payload.get("foregroundEpoch")
        if (
            not isinstance(client_id, str)
            or not isinstance(browser, str)
            or not isinstance(sequence, int)
            or not isinstance(window_id, int)
            or not isinstance(tab_id, int)
            or (domain is not None and not isinstance(domain, str))
            or not isinstance(focused, bool)
            or (request_id is not None and not isinstance(request_id, str))
            or (epoch is not None and not isinstance(epoch, int))
        ):
            return
        if domain is not None:
            try:
                domain = normalize_domain(domain)
            except ValueError:
                # Invalid or non-web contexts are deliberately unresolved.
                domain = None
                focused = False
        result = self._aggregator.browser_snapshot(
            BrowserSnapshot(
                received_ms=monotonic_ms,
                connection_id=connection_id,
                client_instance_id=client_id,
                browser_kind=browser,
                sequence=sequence,
                window_id=window_id,
                tab_id=tab_id,
                domain=domain,
                window_focused=focused,
                snapshot_request_id=request_id,
                requested_foreground_epoch=epoch,
            )
        )
        self._apply_context(result.context)
        if result.snapshot_request is not None:
            self._send_snapshot_requests(result.snapshot_request)

    def tick(self, monotonic_ms: int) -> None:
        self._event_ms = monotonic_ms
        if self._own_foreground or not self._available:
            return
        result = self._aggregator.advance_time(monotonic_ms)
        if result.context_changed:
            self._apply_context(result.context)
            if (
                result.context is not None
                and result.context.resolution.value == "unknown"
            ):
                self._health_sink(
                    "Browser connection is active, but the current site could not "
                    "be confirmed. Website prompts are paused for safety."
                )

    def _apply_context(self, context: ForegroundContext | None) -> None:
        if self._own_foreground or not self._available:
            return
        observation = self._foreground
        if observation is None:
            return
        self._focus.observe_website_context(
            context,
            hwnd=observation.hwnd or 0,
            pid=observation.pid or 0,
            executable_path=observation.executable_path or "",
            browser_name=observation.application_name or "Browser",
            monotonic_ms=self._event_ms,
        )

    def _repeat_snapshot_request(self, browser: str) -> None:
        if self._own_foreground or not self._available:
            return
        context = self._aggregator.current_context
        if context is None or context.application.browser_kind != browser:
            return
        if self._foreground is None:
            return
        # Revalidate at connection receipt time without replaying an old
        # foreground timestamp into the monotonic timer/usage tracker.
        result = self._aggregator.foreground_changed(
            received_ms=self._event_ms, application=context.application
        )
        self._apply_context(result.context)
        if result.snapshot_request is not None:
            self._send_snapshot_requests(result.snapshot_request)

    def system_availability_changed(self, available: bool, monotonic_ms: int) -> None:
        self._available = available
        self._foreground = None
        self._aggregator.foreground_changed(
            received_ms=monotonic_ms, application=ApplicationIdentity("", None)
        )

    def _publish_health(self) -> None:
        counts = {
            "Chrome": sum(
                browser == "chrome" for browser in self._connections.values()
            ),
            "Edge": sum(browser == "edge" for browser in self._connections.values()),
        }
        parts = [f"{name}: {count} profile(s)" for name, count in counts.items()]
        self._health_sink("Browser extension status — " + "; ".join(parts))

    def _send_snapshot_requests(self, request) -> None:
        for connection_id in request.target_connection_ids:
            message = {
                "protocolVersion": 1,
                "messageId": str(uuid.uuid4()),
                "type": "request_snapshot",
                "clientInstanceId": "pending",
                "browser": request.browser_kind,
                "sequence": 0,
                "connectionId": connection_id,
                "payload": {
                    "snapshotRequestId": request.request_id,
                    "foregroundEpoch": request.foreground_epoch,
                },
            }
            self._send(connection_id, message)


def _browser_kind(path: str | None) -> str | None:
    if not path:
        return None
    executable = path.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    if executable == "chrome.exe":
        return "chrome"
    if executable == "msedge.exe":
        return "edge"
    return None
