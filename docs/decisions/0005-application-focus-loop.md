# ADR 0005: Keep the Application Focus Loop Advisory and Event-Driven

- Status: Proposed in Milestone 3; awaiting acceptance
- Date: 2026-09-18

## Context

The first usable product slice must combine Windows foreground observations, recurring schedules, application allowlists, decision prompts, window restoration, and history without turning monitoring callbacks into a second application runtime or blocking normal computer use.

## Decision

The validated WinEvent monitor resolves foreground identities on its own worker and publishes immutable observations into the serialized application queue. A pure `ApplicationFocusPolicy` owns schedule and entry state. It has no Qt, SQLite, or Win32 calls.

Schedule intervals are start-inclusive and end-exclusive. Overnight intervals belong to the date on which they start. When schedules overlap, an application is allowed if a global entry or an entry scoped to any active schedule matches its normalized case-insensitive executable path. Missing time-zone data, unresolved processes, Lock-In itself, and known system shells fail open.

One physical entry identified by window handle and executable path can show at most one prompt. Continue suppresses another prompt until the user leaves that target; returning later is a new entry. Closing the advisory prompt means Continue. Return is offered only when a prior allowed window is known, and Win32 activation remains best effort.

Qt receives prompt and configuration commands only through signals. Prompt-shown and decision events are submitted to the sole database worker. Neither monitor callbacks nor UI callbacks execute SQL.

## Consequences

- Prompts can never forcibly close or block the target application.
- Duplicate WinEvent notifications do not duplicate prompts.
- Rule behavior is deterministic and testable without Windows or Qt.
- A schedule becoming active while one unchanged window remains foreground does not prompt until a fresh entry event.
- Continued-use duration and follow-up prompts remain Milestone 4 work.
