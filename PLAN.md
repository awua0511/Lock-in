# Lock-In Production Implementation Plan

This plan begins after the four risk-validation experiments. Its goal is to turn the validated mechanisms into a maintainable Windows application without coupling experimental entry points directly into production lifecycle code.

## Delivery Strategy

Development proceeds through vertical, testable milestones. Every milestone must leave the repository runnable and must satisfy its acceptance criteria before the next one begins.

The first usable product slice is deliberately narrow:

```text
Create a work schedule
  → add a local application to the allowlist
  → enter a different application during the schedule
  → receive one decision prompt
  → return or continue
  → leave and re-enter to receive a new prompt
```

Website rules, follow-up timing, reviews, and packaging are added only after this application-only loop is reliable.

## Non-Negotiable Boundaries

- The tray client is a single-instance process and the sole SQLite owner.
- WinEvent callbacks and Pipe I/O never manipulate UI widgets directly.
- All external events enter one serialized application event queue.
- `ContextAggregator` is the only component that combines Windows and browser state.
- The rules engine consumes immutable contexts and has no Win32, browser, UI, or database dependency.
- Uncertain browser state produces `pending` or `unknown`, never a guessed domain.
- Prompts are advisory and must never prevent normal computer use.
- All duration calculations use a monotonic clock.
- Sensitive titles, complete URLs, page content, and user input are excluded by default.

## Milestone 0: Preserve the Validated Baseline

### Work

- Create a Git baseline commit and tag for the four completed experiments.
- Keep experiment commands runnable throughout the production refactor.
- Add formatting, static analysis, and test commands with pinned development-tool ranges.
- Define supported versions: Windows 10/11 and current Chrome/Edge releases.
- Record architecture decisions that materially change process or storage boundaries.

### Acceptance criteria

- All existing unit, replay, and communication-harness tests pass from a clean checkout.
- Experiment documentation commands match the installed console entry points.
- No generated capture, log, virtual-environment, or build artifact is tracked.

## Milestone 1: Formal Application Skeleton

### Target structure

```text
src/lock_in/
├── app/                  Lifecycle, coordinator, single-instance startup
├── ui/                   PySide6 tray, settings, and prompt views
├── monitoring/           Production foreground-monitor service
├── context/              ContextAggregator and event models
├── rules/                Pure schedule and allowlist decisions
├── sessions/             Foreground segments and continued-use timing
├── notifications/        Prompt and Windows notification orchestration
├── storage/              SQLite connection, migrations, repositories
├── ipc/                  Named Pipe server and browser connection health
└── platform/windows/     Win32 adapters
```

### Work

- Add the production application entry point and `ApplicationCoordinator`.
- Add a PySide6 event loop and a minimal tray menu with Open and Exit actions.
- Enforce one tray instance using the validated per-user mutex approach.
- Introduce typed application events and one serialized event queue.
- Add privacy-safe rotating file logs and central configuration constants.
- Define clean startup and shutdown ordering for the UI, monitor, IPC, and workers.

### Acceptance criteria

- Starting Lock-In twice leaves exactly one tray process.
- Exit stops all workers, releases the mutex and Pipe, and leaves no child Host.
- Synthetic events can travel from the queue to the coordinator without touching UI from a worker thread.
- A component failure is logged and does not block Windows input or application exit.

## Milestone 2: Domain Model and Local Persistence

### Work

- Define schedule, recurrence, application identity, allowlist, settings, focus-session, and attention-event models.
- Add SQLite with explicit versioned migrations.
- Keep one database worker as the serialized writer.
- Add repositories that return domain objects rather than raw SQLite rows.
- Separate active settings deletion from historical-event deletion.
- Add backup-safe transactions and startup recovery for interrupted migrations.

### Initial tables

```text
schema_migrations
schedules
schedule_recurrences
application_allowlist
website_allowlist
focus_sessions
attention_events
app_settings
```

### Acceptance criteria

- A new profile migrates from an empty directory to the current schema.
- Every migration is tested both forward and after an interrupted transaction.
- Concurrent callers cannot create multiple SQLite writers.
- Schedules and allowlist entries survive restart.
- Clearing history preserves schedules, allowlists, and settings.

## Milestone 3: Application-Only Focus Loop

### Work

- Convert Experiment 1's Win32 adapter into a production monitoring service.
- Maintain a bounded, deduplicated recent-application list.
- Implement pure schedule evaluation, including overlaps and midnight crossings.
- Implement normalized, case-insensitive executable-path matching.
- Connect application contexts to the rules engine.
- Convert Experiment 2's prompt policy into the production prompt controller and PySide6 dialog.
- Record prompt-shown, return, and continue events.

### Acceptance criteria

- Outside an active schedule, no application prompt is eligible.
- An allowlisted application never triggers an entry prompt.
- A non-allowlisted application triggers exactly once per entry.
- Continue does not immediately re-prompt; leaving and re-entering does.
- Return restores an ordinary same-privilege work window when Windows permits it.
- Lock-In, system shells, unresolved processes, and the prompt itself cannot cause prompt loops.
- The complete application-only product slice passes a 30-minute manual smoke test.

## Milestone 4: Foreground Timing and Follow-Up Prompts

### Work

- Represent foreground use as immutable start/stop segments.
- Accumulate time only while the continued target is actually foreground.
- Pause on target exit and stop on lock, sleep, shutdown, or schedule end.
- Resume only after a fresh foreground event.
- Add configurable follow-up thresholds and repeat decisions.
- Preserve timing correctness across wall-clock and time-zone changes.

### Acceptance criteria

- Changing the system clock cannot change measured foreground duration.
- Time spent behind another window is not counted.
- Lock and sleep time is not counted.
- A follow-up prompt cannot fire for a context that has already changed.
- Restart recovery never invents elapsed foreground time.

## Milestone 5: Production Browser Integration

### Work

- Move the Experiment 3 protocol, Host relay, Pipe server, registration, and reconnect behavior behind production interfaces.
- Extend the browser protocol with `request_snapshot`, `snapshotRequestId`, and `foregroundEpoch`.
- Connect WinEvent and browser events to the Experiment 4 `ContextAggregator` through the unified queue.
- Maintain connection health for Chrome, Edge, and each browser profile.
- Implement normalized hostname matching with explicit subdomain behavior.
- Add a non-blocking component-health notice for missing or incompatible extensions.

### Acceptance criteria

- Chrome and Edge can connect concurrently with multiple profiles.
- A browser context is evaluated only when `websiteEvaluationAllowed` is true.
- Stale, late, duplicate, out-of-order, ambiguous, and timed-out snapshots cannot trigger prompts.
- A new foreground epoch never inherits the previous domain.
- Host crash, tray restart, and extension reload recover without duplicating decisions.
- Domain matching never treats `example.com.evil.test` as a subdomain of `example.com`.

## Milestone 6: Reviews and Local Notifications

### Work

- Aggregate daily scheduled time, entry counts, decisions, and non-allowlisted foreground time.
- Add an objective review view with event details.
- Schedule one local Windows notification at the configured review time.
- Add a single catch-up notification after sleep or shutdown when appropriate.
- Apply configurable event-retention cleanup.

### Acceptance criteria

- Aggregates can be reproduced from stored events in deterministic tests.
- A review is sent at most once per local day.
- Time-zone changes do not duplicate or silently skip a review without a recorded reason.
- Review wording contains no reward, punishment, streak, or moral judgment.
- Retention cleanup never deletes current settings or allowlists.

## Milestone 7: Hardening and Distribution

### Work

- Measure idle CPU, working-set memory, startup time, and event latency.
- Test Windows 10/11, multi-monitor DPI combinations, lock/sleep/resume, and elevated targets.
- Package the tray client and Native Host with PyInstaller or Nuitka.
- Install and remove browser manifests cleanly per user.
- Test upgrade, rollback, partial installation, corrupted settings, and migration failure.
- Evaluate code signing, SmartScreen reputation, and extension-store publication.

### Acceptance criteria

- Clean install, upgrade, and uninstall leave the system in a documented state.
- Uninstall removes Native Messaging registration without deleting user data unless requested.
- The packaged build passes the same behavioral and integration suites as source execution.
- Monitoring remains effectively idle when foreground state does not change.
- Known degraded states are visible and never turn into forced blocking.

## Testing Strategy

### Unit tests

- Schedule boundaries, recurrence, overlaps, and midnight crossing.
- Application identity and hostname normalization.
- Rules-engine decisions.
- Prompt and timing state machines.
- Repository behavior and migrations.

### Deterministic replay tests

- Foreground/browser races.
- Duplicate, out-of-order, delayed, and missing messages.
- Lock, sleep, resume, shutdown, and system-time changes.
- Context changes immediately before a prompt is displayed.

### Process integration tests

- Single-instance startup races.
- Multiple Hosts and browser profiles.
- Tray and Host crash recovery.
- Pipe framing, limits, timeouts, and incompatible versions.

### Manual Windows tests

- Foreground activation and restoration restrictions.
- Full-screen and elevated applications.
- Multiple monitors and DPI scales.
- Actual Chrome/Edge profile behavior.
- Windows notification delivery and focus-assist behavior.

## Quality Gates for Every Milestone

- New behavior has automated tests at the lowest practical layer.
- Existing experiment and production tests remain green.
- Worker threads and processes have bounded startup and shutdown.
- No UI action performs blocking Win32, Pipe, or SQLite work.
- Logs contain stable error codes but no page titles, complete URLs, or user input.
- Documentation and GitHub commands are verified from the repository root.
- Changes do not broaden permissions or data collection without an explicit architecture decision.

## Deferred Until After the First Release

- Cloud accounts and synchronization.
- Mobile or macOS clients.
- Rewards, points, streaks, leaderboards, or social features.
- AI classification of whether an activity is productive.
- Enterprise enforcement or anti-circumvention controls.
- Kernel-level monitoring or forced application blocking.
