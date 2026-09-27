# ADR 0006: Measure Continued Use with Foreground-Only Monotonic Segments

- Status: Accepted in Milestone 4
- Date: 2026-09-19

## Context

Follow-up prompts must reflect time the continued target was actually in the foreground. Wall-clock changes, time-zone changes, other windows, lock, sleep, shutdown, and restart must not create elapsed use.

## Decision

Continued use is represented by immutable segments bounded by monotonic millisecond values. A segment begins only after a fresh foreground observation identifies the continued target. Switching to another target ends the segment and invalidates that continued entry. Lock and suspend close the segment; unlock and resume do not restart it until another matching foreground event arrives.

A one-second application timer publishes wall time and monotonic time through the serialized event queue. Wall time reevaluates schedule boundaries only. Monotonic time controls follow-up eligibility. Reaching a threshold latches one prompt; another interval begins only after the user explicitly chooses Continue again.

Timing state is intentionally memory-only. Restart never restores an open segment or calculates duration from persisted wall-clock timestamps. Completed follow-up decisions store the foreground duration already measured at the threshold.

Windows session-lock and power messages enter through a Qt native-event filter and are immediately converted into ordinary serialized application events. Native callbacks do not access policy, storage, or widgets.

## Consequences

- System-clock and time-zone changes cannot alter measured foreground duration.
- Time behind other windows, on the lock screen, or asleep is excluded.
- Restart loses an incomplete interval instead of inventing elapsed time.
- Follow-up prompts remain advisory and cannot fire after the tracked context changes.
- Sub-second persistence of partial intervals is deliberately not provided.
