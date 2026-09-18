from __future__ import annotations

import json
from pathlib import Path

from lock_in.experiments.context_replay import replay_scenario


def test_required_scenario_trace_preserves_word_context_after_late_message() -> None:
    scenario_path = (
        Path(__file__).parents[1] / "scenarios" / "experiment_04_required.json"
    )
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    trace = replay_scenario(scenario)

    assert [entry["atMs"] for entry in trace] == [0, 20, 80, 90, 110]
    assert trace[1]["result"]["reason"] == "stale_snapshot_request"
    assert trace[1]["result"]["context"]["browser"] is None
    assert trace[2]["result"]["context"]["browser"]["domain"] == "github.com"
    assert trace[4]["result"]["reason"] == "no_browser_foreground"
    assert trace[4]["result"]["contextChanged"] is False
    assert trace[4]["result"]["context"] == trace[3]["result"]["context"]
    assert trace[4]["result"]["context"]["websiteEvaluationAllowed"] is False


def load_scenario(name: str) -> list[dict[str, object]]:
    path = Path(__file__).parents[1] / "scenarios" / name
    return replay_scenario(json.loads(path.read_text(encoding="utf-8")))


def test_duplicate_replay_changes_context_only_once() -> None:
    trace = load_scenario("experiment_04_duplicate.json")

    assert trace[1]["result"]["contextChanged"] is True
    assert trace[2]["result"]["disposition"] == "duplicate"
    assert trace[2]["result"]["contextChanged"] is False
    assert trace[2]["result"]["context"] == trace[1]["result"]["context"]


def test_ambiguous_replay_outputs_unknown_without_domain() -> None:
    trace = load_scenario("experiment_04_ambiguous.json")
    final_context = trace[-1]["result"]["context"]

    assert final_context["resolution"] == "unknown"
    assert final_context["browser"] is None
    assert final_context["websiteEvaluationAllowed"] is False


def test_no_reuse_replay_clears_old_domain_then_times_out_unknown() -> None:
    trace = load_scenario("experiment_04_no_reuse.json")
    reentered = trace[3]["result"]["context"]
    timed_out = trace[4]["result"]["context"]

    assert reentered["resolution"] == "pending"
    assert reentered["browser"] is None
    assert timed_out["resolution"] == "unknown"
    assert timed_out["browser"] is None
