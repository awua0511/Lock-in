"""Deterministic ContextAggregator developed by Experiment 4."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class ContextResolution(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class EventDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class ApplicationIdentity:
    executable_path: str
    browser_kind: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserClient:
    connection_id: str
    client_instance_id: str
    browser_kind: str


@dataclass(frozen=True, slots=True)
class BrowserSnapshot:
    received_ms: int
    connection_id: str
    client_instance_id: str
    browser_kind: str
    sequence: int
    window_id: int
    tab_id: int
    domain: str | None
    window_focused: bool
    snapshot_request_id: str | None = None
    requested_foreground_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedBrowserContext:
    connection_id: str
    client_instance_id: str
    browser_kind: str
    window_id: int
    tab_id: int
    domain: str
    sequence: int


@dataclass(frozen=True, slots=True)
class ForegroundContext:
    context_id: str
    foreground_epoch: int
    context_revision: int
    resolution: ContextResolution
    application: ApplicationIdentity
    browser: ResolvedBrowserContext | None
    received_monotonic_ms: int

    @property
    def website_evaluation_allowed(self) -> bool:
        return self.resolution == ContextResolution.RESOLVED and self.browser is not None

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["resolution"] = self.resolution.value
        value["websiteEvaluationAllowed"] = self.website_evaluation_allowed
        return value


@dataclass(frozen=True, slots=True)
class SnapshotRequest:
    request_id: str
    foreground_epoch: int
    browser_kind: str
    target_connection_ids: tuple[str, ...]
    deadline_ms: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AggregationResult:
    disposition: EventDisposition
    reason: str
    context_changed: bool
    context: ForegroundContext | None
    snapshot_request: SnapshotRequest | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "reason": self.reason,
            "contextChanged": self.context_changed,
            "context": self.context.to_dict() if self.context else None,
            "snapshotRequest": (
                self.snapshot_request.to_dict() if self.snapshot_request else None
            ),
        }


@dataclass(slots=True)
class _PendingResolution:
    request: SnapshotRequest
    expected_connections: set[str]
    responded_connections: set[str]
    candidates: dict[str, BrowserSnapshot]


class ContextAggregator:
    """Serialize foreground and browser events into one authoritative context."""

    def __init__(self, *, snapshot_wait_ms: int = 300) -> None:
        if snapshot_wait_ms <= 0:
            raise ValueError("snapshot_wait_ms must be positive")
        self._snapshot_wait_ms = snapshot_wait_ms
        self._clients: dict[str, BrowserClient] = {}
        self._last_sequence: dict[str, int] = {}
        self._seen_sequences: dict[str, set[int]] = {}
        self._foreground_epoch = 0
        self._context_revision = 0
        self._context: ForegroundContext | None = None
        self._pending: _PendingResolution | None = None

    @property
    def current_context(self) -> ForegroundContext | None:
        return self._context

    def connect_client(self, client: BrowserClient) -> None:
        self._clients[client.connection_id] = client

    def disconnect_client(self, connection_id: str) -> None:
        self._clients.pop(connection_id, None)

    def foreground_changed(
        self,
        *,
        received_ms: int,
        application: ApplicationIdentity,
    ) -> AggregationResult:
        self._require_nonnegative_time(received_ms)
        self._foreground_epoch += 1
        self._context_revision = 0
        self._pending = None

        if application.browser_kind is None:
            self._context = self._make_context(
                received_ms=received_ms,
                application=application,
                resolution=ContextResolution.RESOLVED,
                browser=None,
            )
            return AggregationResult(
                EventDisposition.ACCEPTED,
                "application_foreground",
                True,
                self._context,
            )

        target_connections = tuple(
            sorted(
                connection_id
                for connection_id, client in self._clients.items()
                if client.browser_kind == application.browser_kind
            )
        )
        request = SnapshotRequest(
            request_id=f"snapshot-{self._foreground_epoch}",
            foreground_epoch=self._foreground_epoch,
            browser_kind=application.browser_kind,
            target_connection_ids=target_connections,
            deadline_ms=received_ms + self._snapshot_wait_ms,
        )
        self._pending = _PendingResolution(
            request=request,
            expected_connections=set(target_connections),
            responded_connections=set(),
            candidates={},
        )
        # A previous domain is deliberately not copied into a new epoch.
        self._context = self._make_context(
            received_ms=received_ms,
            application=application,
            resolution=ContextResolution.PENDING,
            browser=None,
        )
        return AggregationResult(
            EventDisposition.ACCEPTED,
            "browser_snapshot_requested",
            True,
            self._context,
            request,
        )

    def browser_snapshot(self, snapshot: BrowserSnapshot) -> AggregationResult:
        self._require_nonnegative_time(snapshot.received_ms)
        ordering = self._classify_sequence(snapshot.connection_id, snapshot.sequence)
        if ordering is not None:
            return self._unchanged(ordering, f"sequence_{ordering.value}")

        if self._context is None or self._context.application.browser_kind is None:
            return self._unchanged(
                EventDisposition.REJECTED,
                "no_browser_foreground",
            )
        if snapshot.browser_kind != self._context.application.browser_kind:
            return self._unchanged(EventDisposition.REJECTED, "browser_mismatch")

        if self._pending is not None:
            return self._consume_pending_snapshot(snapshot)

        return self._consume_proactive_snapshot(snapshot)

    def advance_time(self, received_ms: int) -> AggregationResult:
        self._require_nonnegative_time(received_ms)
        pending = self._pending
        if pending is None:
            return self._unchanged(EventDisposition.IGNORED, "no_pending_snapshot")
        if received_ms < pending.request.deadline_ms:
            return self._unchanged(EventDisposition.IGNORED, "deadline_not_reached")
        return self._finalize_pending(received_ms, timed_out=True)

    def _consume_pending_snapshot(
        self, snapshot: BrowserSnapshot
    ) -> AggregationResult:
        pending = self._pending
        assert pending is not None
        request = pending.request
        if snapshot.received_ms > request.deadline_ms:
            # Resolve the timeout first. The late message cannot participate.
            self._finalize_pending(snapshot.received_ms, timed_out=True)
            return self._unchanged(EventDisposition.REJECTED, "snapshot_after_deadline")
        if snapshot.connection_id not in pending.expected_connections:
            return self._unchanged(EventDisposition.REJECTED, "unexpected_connection")
        client = self._clients.get(snapshot.connection_id)
        if client is None or client.client_instance_id != snapshot.client_instance_id:
            return self._unchanged(EventDisposition.REJECTED, "client_mismatch")
        if snapshot.snapshot_request_id != request.request_id:
            return self._unchanged(EventDisposition.REJECTED, "stale_snapshot_request")
        if snapshot.requested_foreground_epoch != request.foreground_epoch:
            return self._unchanged(EventDisposition.REJECTED, "stale_foreground_epoch")

        pending.responded_connections.add(snapshot.connection_id)
        if snapshot.window_focused and snapshot.domain:
            pending.candidates[snapshot.connection_id] = snapshot
        else:
            pending.candidates.pop(snapshot.connection_id, None)

        if pending.responded_connections == pending.expected_connections:
            return self._finalize_pending(snapshot.received_ms, timed_out=False)
        return self._unchanged(EventDisposition.ACCEPTED, "snapshot_candidate_recorded")

    def _consume_proactive_snapshot(
        self, snapshot: BrowserSnapshot
    ) -> AggregationResult:
        context = self._context
        assert context is not None
        bound = context.browser
        if context.resolution != ContextResolution.RESOLVED or bound is None:
            return self._unchanged(EventDisposition.REJECTED, "context_not_resolved")
        if snapshot.snapshot_request_id is not None:
            return self._unchanged(EventDisposition.REJECTED, "stale_snapshot_request")
        if snapshot.connection_id != bound.connection_id:
            return self._unchanged(EventDisposition.REJECTED, "unbound_connection")
        if snapshot.client_instance_id != bound.client_instance_id:
            return self._unchanged(EventDisposition.REJECTED, "client_mismatch")
        if not snapshot.window_focused or not snapshot.domain:
            return self._set_unknown(snapshot.received_ms, "proactive_snapshot_ambiguous")

        self._context_revision += 1
        browser = self._resolved_browser(snapshot)
        self._context = self._make_context(
            received_ms=snapshot.received_ms,
            application=context.application,
            resolution=ContextResolution.RESOLVED,
            browser=browser,
        )
        return AggregationResult(
            EventDisposition.ACCEPTED,
            "proactive_snapshot_applied",
            True,
            self._context,
        )

    def _finalize_pending(
        self, received_ms: int, *, timed_out: bool
    ) -> AggregationResult:
        pending = self._pending
        context = self._context
        assert pending is not None and context is not None
        all_responded = (
            pending.responded_connections == pending.expected_connections
            and bool(pending.expected_connections)
        )
        candidates = list(pending.candidates.values())
        self._pending = None

        if all_responded and len(candidates) == 1:
            self._context_revision += 1
            self._context = self._make_context(
                received_ms=received_ms,
                application=context.application,
                resolution=ContextResolution.RESOLVED,
                browser=self._resolved_browser(candidates[0]),
            )
            return AggregationResult(
                EventDisposition.ACCEPTED,
                "browser_context_resolved",
                True,
                self._context,
            )

        reason = "snapshot_timeout_unknown" if timed_out else "ambiguous_snapshot_unknown"
        return self._set_unknown(received_ms, reason)

    def _set_unknown(self, received_ms: int, reason: str) -> AggregationResult:
        context = self._context
        assert context is not None
        self._context_revision += 1
        self._context = self._make_context(
            received_ms=received_ms,
            application=context.application,
            resolution=ContextResolution.UNKNOWN,
            browser=None,
        )
        return AggregationResult(
            EventDisposition.ACCEPTED,
            reason,
            True,
            self._context,
        )

    def _make_context(
        self,
        *,
        received_ms: int,
        application: ApplicationIdentity,
        resolution: ContextResolution,
        browser: ResolvedBrowserContext | None,
    ) -> ForegroundContext:
        return ForegroundContext(
            context_id=f"context-{self._foreground_epoch}-{self._context_revision}",
            foreground_epoch=self._foreground_epoch,
            context_revision=self._context_revision,
            resolution=resolution,
            application=application,
            browser=browser,
            received_monotonic_ms=received_ms,
        )

    def _resolved_browser(self, snapshot: BrowserSnapshot) -> ResolvedBrowserContext:
        assert snapshot.domain is not None
        return ResolvedBrowserContext(
            connection_id=snapshot.connection_id,
            client_instance_id=snapshot.client_instance_id,
            browser_kind=snapshot.browser_kind,
            window_id=snapshot.window_id,
            tab_id=snapshot.tab_id,
            domain=snapshot.domain.lower().rstrip("."),
            sequence=snapshot.sequence,
        )

    def _classify_sequence(
        self, connection_id: str, sequence: int
    ) -> EventDisposition | None:
        if sequence < 0:
            return EventDisposition.REJECTED
        seen = self._seen_sequences.setdefault(connection_id, set())
        if sequence in seen:
            return EventDisposition.DUPLICATE
        previous = self._last_sequence.get(connection_id)
        seen.add(sequence)
        if previous is not None and sequence < previous:
            return EventDisposition.OUT_OF_ORDER
        self._last_sequence[connection_id] = sequence
        return None

    def _unchanged(
        self, disposition: EventDisposition, reason: str
    ) -> AggregationResult:
        return AggregationResult(disposition, reason, False, self._context)

    @staticmethod
    def _require_nonnegative_time(received_ms: int) -> None:
        if received_ms < 0:
            raise ValueError("received_ms must be non-negative")
