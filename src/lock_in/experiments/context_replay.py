"""Replay JSON event timelines through the Experiment 4 ContextAggregator."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lock_in.context.aggregator import (
    AggregationResult,
    ApplicationIdentity,
    BrowserClient,
    BrowserSnapshot,
    ContextAggregator,
)


class ScenarioError(ValueError):
    pass


def _required(value: dict[str, Any], name: str, expected_type: type) -> Any:
    result = value.get(name)
    if not isinstance(result, expected_type):
        raise ScenarioError(f"{name} must be {expected_type.__name__}")
    return result


def replay_scenario(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    wait_ms = scenario.get("snapshotWaitMs", 300)
    if not isinstance(wait_ms, int):
        raise ScenarioError("snapshotWaitMs must be int")
    aggregator = ContextAggregator(snapshot_wait_ms=wait_ms)

    clients = scenario.get("clients", [])
    if not isinstance(clients, list):
        raise ScenarioError("clients must be a list")
    for raw in clients:
        if not isinstance(raw, dict):
            raise ScenarioError("Each client must be an object")
        aggregator.connect_client(
            BrowserClient(
                connection_id=_required(raw, "connectionId", str),
                client_instance_id=_required(raw, "clientInstanceId", str),
                browser_kind=_required(raw, "browserKind", str),
            )
        )

    events = scenario.get("events")
    if not isinstance(events, list):
        raise ScenarioError("events must be a list")

    trace: list[dict[str, Any]] = []
    previous_ms = -1
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ScenarioError(f"Event {index} must be an object")
        at_ms = _required(event, "atMs", int)
        if at_ms < previous_ms:
            raise ScenarioError("Events must be ordered by atMs")
        previous_ms = at_ms
        event_type = _required(event, "type", str)
        result = _apply_event(aggregator, event_type, at_ms, event)
        trace.append(
            {
                "eventIndex": index,
                "atMs": at_ms,
                "eventType": event_type,
                "result": result.to_dict(),
            }
        )
    return trace


def _apply_event(
    aggregator: ContextAggregator,
    event_type: str,
    at_ms: int,
    event: dict[str, Any],
) -> AggregationResult:
    if event_type == "foreground":
        application = _required(event, "application", dict)
        browser_kind = application.get("browserKind")
        if browser_kind is not None and not isinstance(browser_kind, str):
            raise ScenarioError("browserKind must be string or null")
        return aggregator.foreground_changed(
            received_ms=at_ms,
            application=ApplicationIdentity(
                executable_path=_required(application, "executablePath", str),
                browser_kind=browser_kind,
            ),
        )
    if event_type == "browser_snapshot":
        domain = event.get("domain")
        if domain is not None and not isinstance(domain, str):
            raise ScenarioError("domain must be string or null")
        request_id = event.get("snapshotRequestId")
        if request_id is not None and not isinstance(request_id, str):
            raise ScenarioError("snapshotRequestId must be string or null")
        requested_epoch = event.get("requestedForegroundEpoch")
        if requested_epoch is not None and not isinstance(requested_epoch, int):
            raise ScenarioError("requestedForegroundEpoch must be int or null")
        return aggregator.browser_snapshot(
            BrowserSnapshot(
                received_ms=at_ms,
                connection_id=_required(event, "connectionId", str),
                client_instance_id=_required(event, "clientInstanceId", str),
                browser_kind=_required(event, "browserKind", str),
                sequence=_required(event, "sequence", int),
                window_id=_required(event, "windowId", int),
                tab_id=_required(event, "tabId", int),
                domain=domain,
                window_focused=_required(event, "windowFocused", bool),
                snapshot_request_id=request_id,
                requested_foreground_epoch=requested_epoch,
            )
        )
    if event_type == "advance_time":
        return aggregator.advance_time(at_ms)
    raise ScenarioError(f"Unknown event type: {event_type}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay deterministic events through ContextAggregator.",
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        type=Path,
        default=Path("scenarios/experiment_04_required.json"),
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print indented JSON instead of JSON Lines.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
        if not isinstance(scenario, dict):
            raise ScenarioError("Scenario root must be an object")
        trace = replay_scenario(scenario)
    except (OSError, json.JSONDecodeError, ScenarioError, ValueError) as error:
        print(f"Scenario failed: {error}", file=sys.stderr)
        return 1

    if args.pretty:
        print(json.dumps(trace, ensure_ascii=False, indent=2))
    else:
        for entry in trace:
            print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
