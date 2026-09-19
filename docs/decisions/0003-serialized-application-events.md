# ADR 0003: Serialize Application Events Before UI Delivery

- Status: Accepted in Milestone 1
- Date: 2026-09-18

## Context

Foreground monitoring, browser IPC, persistence, timers, and Qt will eventually run across several threads. Direct widget access from any worker would make ordering nondeterministic and could crash Qt. Allowing each service to invent its own dispatch mechanism would also make shutdown and failure behavior difficult to test.

## Decision

All external and worker events enter one typed, serialized application event queue. `ApplicationCoordinator` consumes those events on the single dispatcher thread and depends only on a framework-independent UI port. The PySide6 implementation of that port emits Qt signals; connected UI slots therefore execute on the Qt application thread.

Managed components start in declared order and stop in reverse order. A component failure becomes a typed event and a privacy-safe log record. Failure handling continues through the remaining components so it cannot block Windows input or application exit.

The production Named Pipe, monitor, storage worker, rules, and session services are not part of this milestone. They will implement the lifecycle and event publisher contracts when introduced.

## Consequences

- Cross-component ordering is explicit and replayable.
- Worker code cannot receive widget references through the coordinator contract.
- Shutdown has one bounded, idempotent path.
- UI updates are asynchronous relative to worker event publication.
- Long-running work must remain outside the coordinator and Qt slots.
