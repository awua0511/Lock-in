# Architecture Decision Records

Architecture Decision Records (ADRs) preserve decisions that constrain multiple modules or processes. New ADRs use the next four-digit number and remain immutable after acceptance; a later decision supersedes an earlier one instead of silently rewriting it.

| ADR | Status | Decision |
| --- | --- | --- |
| [0001](0001-single-owner-process-boundaries.md) | Accepted by experiment baseline | Single tray owner with stateless Native Messaging relays. |
| [0002](0002-explicit-browser-context-correlation.md) | Accepted by experiment baseline | Explicit request-and-epoch browser correlation. |
| [0003](0003-serialized-application-events.md) | Accepted in Milestone 1 | Serialized application events with a Qt signal bridge. |
| [0004](0004-single-sqlite-writer.md) | Accepted in Milestone 2 | One serialized SQLite owner with atomic migrations and typed repositories. |
| [0005](0005-application-focus-loop.md) | Accepted in Milestone 3 | Pure application entry policy with advisory Qt prompts. |
| [0006](0006-monotonic-foreground-timing.md) | Accepted in Milestone 4 | Monotonic, foreground-only continued-use timing. |
| [0007](0007-local-daily-reviews.md) | Implemented; pending M6 acceptance | Independent usage checkpoints, stable local dates, and at-most-once daily notification attempts. |
| [0008](0008-recoverable-per-user-distribution.md) | Implemented; pending M7 acceptance | Validated per-user bundles, recoverable activation and presentation-only UI changes. |
