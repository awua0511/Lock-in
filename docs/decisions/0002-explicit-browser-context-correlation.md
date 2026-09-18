# ADR 0002: Explicit Browser Context Correlation

- Status: Accepted by experiment baseline
- Date: 2026-09-18

## Context

WinEvent foreground changes and browser-extension snapshots originate in different processes. Receipt timestamps and monotonically increasing browser sequences cannot prove that a cached or delayed domain belongs to the current physical foreground activation.

## Decision

- Every physical foreground change increments `foregroundEpoch`.
- Entering a supported browser creates a new context with `pending` resolution and no copied domain.
- The tray client sends a unique `snapshotRequestId` bound to that epoch.
- An initial browser snapshot must echo both values before it can resolve the context.
- Missing, ambiguous, late, duplicate, or out-of-order information cannot produce a guessed domain.
- Uncertain state becomes `pending` or `unknown`, with website evaluation disabled.
- Leaving the browser invalidates its binding immediately.

## Consequences

- The extension protocol must support request/response correlation in addition to proactive tab updates.
- Website rules may be delayed briefly while a browser context is pending.
- Multi-profile ambiguity intentionally suppresses a prompt rather than risking a false prompt.
- The previous domain is never a fallback.

## Validation

Experiment 4 replayed stale, late, duplicate, out-of-order, missing, and ambiguous events and verified that only an explicitly correlated domain becomes eligible for website evaluation.
