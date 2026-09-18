# Experiment 4: Context Aggregator Replay Simulator

This experiment validates `ContextAggregator` with deterministic, replayable events before it is connected to real WinEvent or browser-extension inputs.

It performs no browser automation, Named Pipe communication, prompting, allowlist evaluation, schedule evaluation, or database access.

## Required Timeline

The checked-in scenario reproduces this race:

```text
0 ms    Chrome becomes foreground
20 ms   stale youtube.com snapshot arrives
80 ms   current github.com snapshot arrives
90 ms   Word becomes foreground
110 ms  delayed youtube.com snapshot arrives
```

The scenario is stored in [scenarios/experiment_04_required.json](scenarios/experiment_04_required.json).

When Chrome becomes foreground, the aggregator creates:

```text
foregroundEpoch: 1
snapshotRequestId: snapshot-1
resolution: pending
domain: none
```

An initial browser snapshot may resolve this pending context only when it echoes both the current `snapshotRequestId` and `foregroundEpoch`. This is intentional: arrival time and sequence ordering alone cannot prove that a cached tab snapshot belongs to the new foreground activation.

## Run the Tests

Run the complete test suite:

```powershell
.venv\Scripts\python -m pytest -v
```

Run the required timeline through the simulator:

```powershell
.venv\Scripts\lock-in-context-replay `
    scenarios\experiment_04_required.json `
    --pretty
```

Replay the other acceptance scenarios by replacing the filename with:

```text
scenarios\experiment_04_duplicate.json
scenarios\experiment_04_ambiguous.json
scenarios\experiment_04_no_reuse.json
```

The important results are:

| Time | Expected result |
| ---: | --- |
| 0 ms | `pending`, no browser domain, request `snapshot-1` issued. |
| 20 ms | `stale_snapshot_request`, no context change, no domain. |
| 80 ms | `resolved` to `github.com`. |
| 90 ms | application-only Word context, website evaluation disabled. |
| 110 ms | `no_browser_foreground`, no context change, Word remains current. |

The 110 ms event must have `contextChanged: false` and `websiteEvaluationAllowed: false`. The simulator contains no reminder component; this flag is the contract proving that downstream website rules or reminders are not eligible to run.

## Safety Rules Under Test

### Initial browser correlation

- Every physical foreground change increments `foregroundEpoch`.
- A browser foreground event creates a new pending context with no copied domain.
- A unique snapshot request is bound to that epoch.
- Cached, proactive, previous-request, and previous-epoch messages cannot resolve the pending context.

### Multiple profiles

- The request targets every connected profile for the foreground browser type.
- Resolution occurs only after every expected profile responds and exactly one valid focused candidate exists.
- Multiple focused candidates produce `unknown`.
- A missing profile response produces `unknown` at the deadline.

### Ordering

- An exact repeated `connectionId + sequence` is `duplicate` and changes nothing.
- A previously unseen sequence below the connection high-water mark is `out_of_order` and changes nothing.
- Ordering is tracked independently for each Host connection.

### Leaving the browser

- Switching to a normal application immediately discards the pending or resolved browser binding.
- A browser message received afterward is rejected and cannot change the application context.
- Returning to the browser starts a new epoch in `pending`; the previous domain is never copied.

### Uncertainty

The aggregator outputs `unknown` with no domain when:

- The snapshot deadline expires without every expected response.
- No valid focused candidate exists.
- More than one browser profile claims to be the focused candidate.
- A resolved profile later reports an ambiguous proactive state.

`pending` and `unknown` both set `websiteEvaluationAllowed` to false.

## Additional Scenarios

Copy the checked-in JSON file and edit its events. Supported event types are:

```text
foreground
browser_snapshot
advance_time
```

Events must be ordered by `atMs`. The simulator uses those values as a monotonic clock and never uses the system wall clock.

## Acceptance Criteria

Experiment 4 passes when the automated tests and required replay prove all of the following:

- `youtube.com` is never attached to the new Chrome context at 20 ms.
- `github.com` is the only domain resolved for the Chrome epoch.
- The delayed 110 ms message cannot replace Word or enable website evaluation.
- Duplicate and out-of-order messages cannot change the context.
- Ambiguous and timed-out browser states become `unknown` with no domain.
- A new browser epoch begins without reusing the previously resolved domain.

After these criteria and the prior three experiments pass, the validated adapters and state machines can be assembled into the formal application structure.
