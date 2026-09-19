# Milestone 2: Domain Model and Local Persistence

Milestone 2 provides durable local data boundaries. It deliberately does not add settings forms, schedule evaluation, foreground monitoring, prompts, or browser behavior.

## Delivered Scope

- Immutable domain models for schedules, one-time and weekly recurrence, application identity, application and website allowlists, settings, focus sessions, and attention events.
- Validation for model invariants, offset-aware history timestamps, and normalized hostnames.
- Two explicit SQLite migrations covering all eight planned tables.
- One database worker thread that exclusively owns the connection and serializes concurrent callers.
- A per-process registry that rejects a second writer for the same resolved database path.
- Typed repositories for schedules, allowlists, settings, sessions, events, and history deletion.
- Atomic repository writes and per-version migration transactions.
- Recovery after an interrupted migration and a SQLite backup before upgrading an existing profile.
- Production lifecycle integration: startup initializes/migrates the database, while Exit drains and closes the database worker before releasing the application mutex.

Application and website allowlist entries may be global or associated with a schedule. Deleting a schedule cascades its scoped recurrence and allowlist configuration, while historical sessions retain their facts with a nullable schedule reference.

## Database Location

The default database is:

```text
%LOCALAPPDATA%\LockIn\lock-in.sqlite3
```

The pre-migration backup, created only when an older non-empty profile requires an upgrade, is:

```text
%LOCALAPPDATA%\LockIn\lock-in.pre-migration.backup.sqlite3
```

## Automated Acceptance

Run the Milestone 2 tests:

```powershell
.\.venv\Scripts\python -m pytest `
    tests\test_domain_models.py `
    tests\test_storage_migrations.py `
    tests\test_storage_repositories.py `
    -v
```

Then run the complete quality gate:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

The tests prove:

- an empty profile reaches the current schema;
- each migration version rolls back cleanly and resumes after reconnection;
- an older database is backed up before upgrade;
- concurrent callers execute on exactly one writer thread;
- a second worker cannot own the same database path;
- schedules, recurrence, allowlists, and settings survive worker restart;
- a failed operation does not kill the worker;
- clearing history preserves all active configuration;
- the production process creates the schema and closes cleanly.

## Manual Acceptance

Ensure Lock-In is not already running, then start it:

```powershell
.\.venv\Scripts\lock-in.exe
```

Confirm that the window and tray still behave as in Milestone 1, then choose **Exit**. Run the read-only schema inspector, which prints no schedule, allowlist, or history content:

```powershell
.\.venv\Scripts\lock-in-inspect-database.exe
```

Expected migration output:

```text
"migrations": [
  {"name": "configuration", "version": 1},
  {"name": "history", "version": 2}
]
```

The table list must include:

```text
app_settings
application_allowlist
attention_events
focus_sessions
schedule_recurrences
schedules
schema_migrations
website_allowlist
```

There is intentionally no schedule or allowlist editing UI in this milestone. Persistence behavior is accepted through deterministic repository tests rather than manual database modification.

## Acceptance Boundary

Accept this milestone only when its targeted tests, the complete quality gate, application startup/Exit, and schema inspection all pass. Acceptance does not authorize Milestone 3 implementation.
