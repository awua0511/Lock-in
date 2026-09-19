# ADR 0004: Use One Serialized SQLite Owner

- Status: Proposed in Milestone 2; awaiting acceptance
- Date: 2026-09-18

## Context

Settings, schedules, allowlists, focus sessions, and attention events must survive restart. UI callbacks and future monitor or IPC workers will issue storage requests concurrently, but sharing SQLite connections across those threads would weaken ordering and shutdown guarantees.

## Decision

The single-instance tray process is the only process allowed to open the product database. Within that process, one `DatabaseWorker` thread owns one SQLite connection. Callers submit operations and receive futures; repositories return immutable domain objects rather than connections or rows.

Schema changes use consecutive, named migrations. Each migration version runs in its own `BEGIN IMMEDIATE` transaction and records its version only after all statements succeed. An interrupted version rolls back and is retried at the next startup. Before upgrading a non-empty older database, SQLite's online backup API writes one pre-migration backup.

SQLite uses foreign-key enforcement, WAL journaling, and full synchronous durability. Focus timestamps are normalized to UTC offsets before storage; schedule and review times remain local wall-clock values with an explicit schedule time-zone identifier.

History deletion is a dedicated repository operation that deletes only `attention_events` and `focus_sessions`. It cannot delete schedules, recurrences, allowlists, or settings.

## Consequences

- Concurrent callers cannot create concurrent writers for the same database path in one tray process.
- The UI never performs SQL or owns a database connection.
- Repository calls are asynchronous and must not be awaited by blocking the Qt UI thread.
- A failed task fails its own future without terminating the worker.
- Database migrations and their backup files become compatibility commitments.
