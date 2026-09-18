# ADR 0001: Single-Owner Process Boundaries

- Status: Accepted by experiment baseline
- Date: 2026-09-18

## Context

Chromium launches a Native Messaging Host per extension connection. Multiple browsers and profiles can therefore create concurrent Host processes, while schedules, rules, activity state, and SQLite require one authoritative owner.

## Decision

- The Windows tray client is a per-user single-instance process.
- The tray client is the sole owner of rule state and SQLite.
- Native Messaging Hosts are short-lived, stateless framing and relay processes.
- Hosts connect to the tray client through a per-user Named Pipe.
- A Host never opens SQLite, evaluates rules, or displays product UI.
- Concurrent Hosts may race to start the tray client; a named mutex allows exactly one tray instance to survive.

## Consequences

- Tray restart disconnects Hosts; extensions reconnect with bounded backoff.
- IPC and protocol compatibility become explicit release concerns.
- Database concurrency is simplified because no other process accesses it.
- A broken Host affects one extension connection rather than corrupting application state.

## Validation

Experiment 3 validated Chrome/Edge-style concurrent clients, multiple profiles, startup races, Host failure, tray restart, extension reload, ordering, and timeouts.
