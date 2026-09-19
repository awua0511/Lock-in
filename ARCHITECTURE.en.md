# Lock-In Architecture

English

This document describes the technical architecture of the Lock-In Windows client and browser extension. For product features and user-facing behavior, see [README.md](README.md). For the production delivery sequence, see [PLAN.md](PLAN.md).

## Technical Goals

- Use event-driven foreground monitoring instead of high-frequency polling.
- Monitor applications and browsers without requiring administrator privileges.
- Store all settings and behavior records locally by default.
- Use a stable, versioned protocol between the desktop client and browser extension.
- Separate the rules engine from operating-system integration so the client can later migrate to C++.
- Ensure that failures in monitoring or communication never prevent normal computer use.

## Technology Stack

The first release is planned around the following stack:

| Component | Technology |
| --- | --- |
| Windows client | Python 3.12+ |
| Desktop UI | PySide6 |
| Windows APIs | pywin32 / ctypes |
| Local database | SQLite |
| Browser extension | Manifest V3 + JavaScript/TypeScript |
| Extension-to-client communication | Native Messaging |
| Windows packaging | PyInstaller or Nuitka |

If the Python implementation encounters unacceptable startup time, resource usage, antivirus false positives, or distribution issues, the resident desktop component can migrate to C++/Qt while retaining the database schema and Native Messaging protocol.

## High-Level Architecture

```text
┌────────────────────────┐
│ Chromium Extension     │
│ Tabs / Windows / Domain│
└───────────┬────────────┘
            │ Native Messaging (stdio)
┌───────────▼────────────┐
│ Native Messaging Host │  Stateless relay launched per connection
└───────────┬────────────┘
            │ Per-user Named Pipe
┌───────────▼─────────────────────────────────────────┐
│           Windows Tray Client (single instance)    │
│                                                    │
│ WinEvent monitor ─┐                                │
│                   ├→ ContextAggregator → Rules → UI│
│ Browser messages ─┘                         │      │
│                                             └→ Data│
└───────────┬────────────────────────────────────────┘
            │ Sole database owner
┌───────────▼────────────┐
│ Local SQLite Database │
│ Schedules / Rules /   │
│ Events                │
└───────────────────────┘
```

Process boundaries must follow these rules:

- The Windows tray client is a single-instance process and the sole owner of rule state and SQLite.
- A browser may launch one Native Messaging Host for each extension connection; every Host is stateless.
- A Host validates, frames, and relays messages only. It never evaluates rules, displays UI, or accesses SQLite.
- Bidirectional messages between extensions and the client pass through the Host and a per-user Named Pipe.
- Multiple browsers, browser profiles, and Host processes may connect to the same tray client concurrently.

## Module Boundaries

The Windows client should be divided into modules similar to the following:

```text
lock_in/
├── app/                  Entry point and application lifecycle
├── ui/                   PySide6 windows, tray, and dialogs
├── monitoring/           Foreground window and browser monitoring
├── context/              Cross-source aggregation, ordering, and validity
├── rules/                Schedule and allowlist evaluation
├── sessions/             Work sessions and foreground timing
├── notifications/        Prompts and evening notifications
├── storage/              SQLite repositories and migrations
├── ipc/                  Named Pipe server and connection management
└── platform/windows/     Win32 API wrappers

native_host/
├── main.py               Native Messaging framing
├── validation.py         Protocol version and message validation
└── pipe_client.py        Per-user Named Pipe client

browser_extension/
├── manifest.json
├── service-worker.js
├── native-connection.js
├── context-snapshot.js
├── options.html
└── options.js
```

The UI must not call Win32 APIs or execute SQL directly. Operating-system events are first converted into internal events and then evaluated by the rules engine.

## Foreground Application Monitoring

### Event Source

Use `SetWinEventHook` to subscribe to `EVENT_SYSTEM_FOREGROUND`:

```text
Foreground window changes
      ↓
WinEvent callback receives HWND
      ↓
Event is placed on the application queue
      ↓
Worker resolves the application identity
      ↓
Rules engine evaluates the context
```

The callback must not perform database queries or complex UI work, because doing so could block the system event thread. The thread that registers the hook must maintain a Windows message loop and call `UnhookWinEvent` during shutdown.

### Application Identity Resolution

Resolve ordinary Win32 applications using this flow:

```text
HWND
  ↓ GetWindowThreadProcessId
PID
  ↓ OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)
Process handle
  ↓ QueryFullProcessImageNameW
Executable path
  ↓ Path normalization
ApplicationIdentity
```

Example internal identity:

```json
{
  "kind": "win32",
  "displayName": "Visual Studio Code",
  "executablePath": "C:\\Program Files\\Microsoft VS Code\\Code.exe"
}
```

Path comparison must:

- Use normalized absolute paths.
- Compare Windows paths case-insensitively.
- Account for symbolic links and short-path forms.
- Tolerate a process exiting while its identity is being resolved.
- Avoid repeatedly prompting for system processes whose identities cannot be resolved.

### Packaged Applications

Microsoft Store, MSIX, and some UWP applications can have versioned installation paths that change after an update. These applications should be identified primarily by Package Family Name:

```json
{
  "kind": "packaged",
  "displayName": "Microsoft To Do",
  "packageFamilyName": "Microsoft.Todos_8wekyb3d8bbwe"
}
```

The first release may fully support only Win32 applications and treat packaged-application support as a separate iteration.

## Recently Used Applications

The foreground monitor maintains a deduplicated list of recently active applications containing:

- Display name.
- Executable path or package identity.
- Application icon.
- Last activation time.

The following should not appear in the recent list:

- Lock-In itself.
- Background processes without a valid top-level window.
- Known Windows shell windows.
- Temporary windows whose identities cannot be safely resolved.

The list should have a fixed maximum size and be ordered by most recent activation.

## Browser Website Detection

The Windows client can determine that a browser is in the foreground, but it cannot reliably retrieve the current tab URL. Website allowlisting is therefore implemented by a browser extension.

The extension listens for:

- `tabs.onActivated` for active-tab changes.
- `tabs.onUpdated` for URL updates.
- `webNavigation` for top-level navigation.
- Browser-window focus changes.
- Current-context snapshot requests forwarded by the desktop client.

Each extension instance in a browser profile generates and persists a random `clientInstanceId` on first run. It must not contain a username, profile path, or other personally identifying information. Every state message also carries a monotonically increasing `sequence` so duplicated and out-of-order messages can be discarded.

The extension sends only normalized context snapshots:

```json
{
  "protocolVersion": 1,
  "event": "browser_context_snapshot",
  "snapshotRequestId": "uuid-from-request-snapshot",
  "requestedForegroundEpoch": 912,
  "clientInstanceId": "550e8400-e29b-41d4-a716-446655440000",
  "browser": "edge",
  "sequence": 184,
  "windowId": 42,
  "tabId": 108,
  "documentId": "optional-browser-document-id",
  "windowFocused": true,
  "scheme": "https",
  "domain": "youtube.com",
  "timestamp": "2026-09-16T13:08:00-04:00"
}
```

By default, it does not send:

- URL query parameters.
- Page titles.
- URL fragments.
- Page content.
- Form or keyboard input.

The first release prioritizes Chromium-based browsers:

- Google Chrome.
- Microsoft Edge.
- Brave.

### Context Aggregation and Temporal Correlation

Windows foreground events and browser-extension events originate in different processes and cannot be joined using timestamps alone. The desktop client must use a `ContextAggregator` to produce one authoritative current context.

The aggregator maintains two state families:

```text
WindowsForegroundState
- foregroundEpoch: increments on every physical foreground change
- hwnd / pid / applicationIdentity
- browserKind, when the application is supported
- receivedMonotonicTime

BrowserClientState
- connectionId / clientInstanceId / browserKind
- sequence
- windowId / tabId / documentId
- windowFocused / domain
- receivedMonotonicTime
- healthState
```

Correlation rules:

1. When a regular application enters the foreground, immediately create an application-only context.
2. When a supported browser enters the foreground, create a `PendingBrowserContext`, generate a unique `snapshotRequestId` bound to the new `foregroundEpoch`, and send both values in `request_snapshot` to every connected extension instance for that browser type.
3. An initial snapshot may resolve the pending context only when it echoes the current `snapshotRequestId` and `foregroundEpoch`, has a supported protocol version and newer `sequence`, claims a focused window, and arrives inside the validity window. Arrival time alone is never proof of correlation.
4. Resolve only after every expected healthy extension instance responds and exactly one valid focused candidate exists. A cached or proactive snapshot cannot resolve a pending context.
5. If responses are missing at the deadline, multiple candidates are equally credible, or no valid candidate exists, produce `UnknownBrowserContext`. Never reuse the previous domain.
6. While the browser remains foreground, only a proactive snapshot from the already bound extension instance may increment `contextRevision` and create a new logical context without changing the Windows `foregroundEpoch`.
7. When Windows switches to another application, invalidate the previous browser context immediately. Late browser messages may refresh the cache but cannot trigger a prompt.

Suggested initial parameters:

```text
Snapshot wait limit: 300 ms
Proactive snapshot TTL: 2 s
Heartbeat interval: 15 s
Connection stale threshold: 45 s
```

These parameters must be centrally configurable and tuned through multi-window, multi-profile, and high-load testing. All timeout and freshness decisions use the desktop client's monotonic receipt clock. Extension wall-clock timestamps are diagnostic only and must not order cross-process events.

Aggregator output:

```json
{
  "contextId": "uuid",
  "foregroundEpoch": 912,
  "contextRevision": 3,
  "resolution": "resolved",
  "application": {
    "kind": "win32",
    "executablePath": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  },
  "browser": {
    "connectionId": "uuid",
    "clientInstanceId": "uuid",
    "windowId": 42,
    "tabId": 108,
    "domain": "github.com"
  },
  "receivedMonotonicMs": 48192033
}
```

`resolution` is one of `resolved`, `pending`, or `unknown`. The rules engine evaluates website allowlists only for a `resolved` context.

## Native Messaging

The browser extension first communicates with a Native Messaging Host. The Host then communicates with the running tray client over a per-user Named Pipe. Native Messaging and the Named Pipe use the same JSON envelope but different transport framing.

### Component Responsibilities

**Browser extension**

- Captures the current browser window and tab state.
- Maintains an increasing `sequence`.
- Responds to `request_snapshot` forwarded by the desktop client.
- Reconnects with capped exponential backoff after a disconnect.

**Native Messaging Host**

- Is launched by the browser per connection and may have a shorter lifetime than the desktop client.
- Reads and writes Native Messaging's four-byte little-endian length prefix and UTF-8 JSON body.
- Validates message size, JSON structure, and protocol version.
- Assigns a random `connectionId` to its process.
- Connects to the desktop client's per-user Named Pipe and relays messages bidirectionally.
- Never accesses the database, evaluates allowlist rules, or displays UI.

**Windows tray client**

- Uses a per-user mutex to guarantee a single instance.
- Accepts multiple Host connections as the Named Pipe Server.
- Owns connection health, browser snapshots, and the ContextAggregator.
- Is the sole process allowed to read or write SQLite.
- Notifies connected peers and closes the Pipe during shutdown.

### Startup and Reconnection

```text
Extension calls connectNative
        ↓
Browser launches Native Messaging Host
        ↓
Host attempts to connect to per-user Named Pipe
        ├── Success → hello handshake → bidirectional relay
        └── Missing
              ↓
           Launch tray client --background
              ↓
           Retry Pipe connection for a bounded period
              ├── Success → hello handshake
              └── Failure → return host_unavailable and exit
```

The client handles concurrent startup races through its mutex: several Hosts may attempt to launch it, but only one tray process survives. Host retries must have explicit limits and must never loop indefinitely.

After a client upgrade or restart, existing Hosts disconnect and exit; extensions subsequently call `connectNative` again. The architecture must not assume a Native Messaging connection is permanent.

### Per-User Named Pipe

The Pipe name includes the protocol major version and a value derived from the current user identity, for example:

```text
\\.\pipe\LockIn.<user-sid-hash>.v1
```

Security requirements:

- The Pipe ACL allows access only to the current interactive user.
- The client rejects peers from another session or user.
- Enforce a per-message limit such as 64 KiB.
- Apply connection read/write and idle timeouts.
- The Host never accepts an arbitrary Pipe path from its command line.
- The Host generates `connectionId`; the extension cannot choose it.

### Host Manifest and Browser Identity

Each browser installation receives a corresponding Native Messaging Host manifest. Its `allowed_origins` contains explicit production extension IDs. Development and production extension IDs are maintained separately; wildcards are not used.

The browser enforces which extensions may launch the Host from this manifest, but the desktop client still validates the Host's `hello` message, protocol version, and browser type. Anonymous `clientInstanceId` values distinguish extension instances in different browser profiles.

### Protocol Envelope

Recommended message envelope:

```json
{
  "protocolVersion": 1,
  "messageId": "uuid",
  "connectionId": "uuid",
  "type": "browser_context_snapshot",
  "payload": {
    "browser": "edge",
    "clientInstanceId": "uuid",
    "sequence": 184,
    "windowFocused": true,
    "domain": "youtube.com"
  },
  "timestamp": "2026-09-16T13:08:00-04:00"
}
```

The first protocol version defines at least:

```text
hello / hello_ack
request_snapshot
browser_context_snapshot
heartbeat / heartbeat_ack
protocol_error
host_unavailable
shutdown
```

Protocol rules:

- Do not accept business messages before the `hello` handshake completes.
- Reject unsupported major versions; additional fields remain backward-compatible.
- Process a given `connectionId + sequence` snapshot only once.
- Return `protocol_error` for an unknown message type without crashing the client.
- Logs contain message type, size, and error code only—not domain values.

The client distinguishes these states for every browser connection:

- Connected with current tab data.
- Connected and waiting for the first snapshot.
- Browser running but extension not connected.
- Extension connected but current page cannot be identified.
- Extension not installed.
- Heartbeat timeout or incompatible protocol.

An unknown or unhealthy state must not be treated as a non-allowlisted website, and the previous domain must never be silently reused. During a work period, the client displays one non-blocking component-health notification.

## Rules Engine

The rules engine receives a unified `ForegroundContext`:

```json
{
  "contextId": "uuid",
  "foregroundEpoch": 912,
  "contextRevision": 3,
  "resolution": "resolved",
  "application": {
    "kind": "win32",
    "executablePath": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  },
  "browser": {
    "connectionId": "uuid",
    "clientInstanceId": "uuid",
    "windowId": 42,
    "tabId": 108,
    "domain": "github.com"
  },
  "receivedMonotonicMs": 48192033
}
```

Evaluation order:

```text
Is an active work schedule in effect?
        ↓ No
Do nothing
        ↓ Yes
Is the current application on the base system allowlist?
        ↓ Yes
Do nothing
        ↓ No
Is the current application a supported browser?
        ├── No  → Evaluate the application allowlist
        └── Yes
             ├── pending  → Wait for a snapshot; do not prompt
             ├── unknown  → Do not prompt; update component health
             └── resolved → Evaluate the domain and website allowlist
```

The rules engine never reads extension caches or Windows state directly. It consumes only immutable snapshots emitted by the ContextAggregator. Every decision includes `contextId`, `foregroundEpoch`, and `contextRevision`; immediately before displaying a prompt, the client verifies that these values still describe the current context so a late decision cannot prompt for a page the user has already left.

Domain rules must operate on a parsed hostname rather than a raw string suffix. For example, when subdomains of `example.com` are allowed, `docs.example.com` may match while `example.com.evil.test` must not.

## Prompt State Machine

```text
Allowed
  │ Switch to non-allowlisted content
  ▼
Prompting
  ├── Return   → Returned → Allowed
  └── Continue → Continuing
                      │ Follow-up threshold reached
                      ▼
                   Prompting
                      │ Target loses foreground
                      ▼
                    Allowed
```

Prompt deduplication must account for:

- The Lock-In prompt becoming the foreground window.
- Duplicate foreground events from Windows.
- A browser sending both tab-activation and navigation events.
- Multiple events for the same target within a short interval.
- A new prompt being required after the user leaves and later re-enters a target.

## Foreground Time Tracking

Use application activation and deactivation as timing boundaries:

```text
Non-allowlisted target enters foreground → Start or resume timing
Another target enters foreground         → Stop the current segment
Screen locks or system sleeps            → Stop timing
System resumes                           → Wait for a new foreground event
```

Use a monotonic clock for duration calculations so system time or time-zone changes cannot corrupt elapsed time. Wall-clock timestamps are used only for display and daily grouping.

## Local Data

Recommended SQLite tables:

```text
schedules
schedule_recurrences
application_allowlist
website_allowlist
focus_sessions
attention_events
app_settings
schema_migrations
```

Schema versions 1 and 2 implement these tables. Configuration tables are created before history tables so a failed history upgrade cannot invalidate active schedules or allowlists. Application and website allowlist rows contain an optional `schedule_id`: `NULL` represents a global user entry, while a value scopes the entry to one schedule. Foreign keys cascade schedule-owned configuration and set historical session references to `NULL` when a schedule is deleted.

The production process owns one `DatabaseWorker`. That worker opens and migrates SQLite on its own thread, then serializes repository operations submitted by concurrent callers. A second worker for the same resolved path is rejected within the process. UI code receives futures and domain objects; it never receives SQLite connections or rows.

Each migration version runs in a separate `BEGIN IMMEDIATE` transaction. A failed or interrupted version is not recorded and is retried after restart. Before upgrading a non-empty older profile, the client uses SQLite's backup API to create `lock-in.pre-migration.backup.sqlite3`.

### Application Allowlist Record

```json
{
  "id": "uuid",
  "kind": "win32",
  "displayName": "Visual Studio Code",
  "executablePath": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
  "packageFamilyName": null,
  "enabled": true
}
```

### Website Allowlist Record

```json
{
  "id": "uuid",
  "domain": "github.com",
  "includeSubdomains": true,
  "enabled": true
}
```

### Attention Event

```json
{
  "id": "uuid",
  "focusSessionId": "uuid",
  "occurredAt": "2026-09-16T13:08:00-04:00",
  "targetType": "website",
  "targetKey": "youtube.com",
  "decision": "continue",
  "foregroundSeconds": 300
}
```

All database changes must use versioned migrations. Deleting event history must preserve the user's active settings and allowlists.

## Threading Model

Recommended execution contexts:

- UI main thread for the PySide6 event loop and window rendering.
- WinEvent thread for hook registration and the Windows message loop.
- Pipe Server I/O for multiple Native Host connections and asynchronous reads and writes.
- ContextAggregator running in one serialized execution context for Windows and browser events.
- Database worker thread as the desktop client's sole SQLite writer, using short transactions.
- Native Messaging Host as an external short-lived browser-launched process, not part of the client thread model.

All cross-thread and cross-process events pass through a unified queue before the ContextAggregator, rules engine, or UI consumes them. WinEvent and Pipe I/O callbacks must never manipulate PySide6 widgets directly. SQLite connections are not shared across threads, and neither the Native Messaging Host nor the browser extension may open the database file.

## Local Notifications

The evening review is triggered by a local schedule. Notification content is generated from data already aggregated for the day and does not depend on a network service.

If sleep causes the notification time to be missed, the client may send a catch-up notification after resume when:

- The day's review has not already been sent.
- The current time remains inside a configured catch-up window.

Only one catch-up notification should be sent.

## Privacy and Security

- Do not require a user account by default.
- Do not transmit telemetry or activity records by default.
- Do not read page content or user input.
- Do not store complete URLs.
- Accept Native Messaging connections only from declared extension IDs.
- Do not write sensitive URLs, command-line arguments, or window contents to logs.
- Store the database and logs in the current user's application-data directory.
- When the user clears data, remove both behavior records and application logs.

## Error Handling

The following failures must never prevent normal computer use:

- Failure to read a foreground process path.
- A target process exiting during identity resolution.
- Browser extension disconnection.
- Temporary database write failure.
- Failure to display a prompt.
- Windows notifications being unavailable.

The default policy is to record a diagnostic error that contains no sensitive data and skip the current prompt. Lock-In does not follow a “block when uncertain” policy.

## Packaging and Distribution

Personal testing can run directly from source. Production builds may use PyInstaller or Nuitka and include:

- The Windows client.
- Native Messaging Host registration data.
- SQLite initialization and migration files.
- Browser extension installation instructions.

Before public distribution, evaluate:

- Windows code signing.
- SmartScreen behavior for unsigned installers.
- An automatic update mechanism.
- Chrome Web Store and Microsoft Edge Add-ons publication.
- Cleanup of Native Messaging registration during uninstall.

## Testing Priorities

- Multiple monitors and different DPI scaling factors.
- Overlapping work schedules.
- Work schedules that cross midnight.
- System sleep, resume, and lock-screen transitions.
- System time and time-zone changes.
- Launchers whose executable differs from the actual foreground process.
- Application updates that change executable paths.
- Multi-window Chrome, Edge, and Brave sessions.
- Incognito windows and internal browser pages.
- Missing, disabled, or disconnected browser extensions.
- The prompt window triggering its own foreground event.
- Session recovery after an unexpected client exit.

## Implementation Order

Risk-validation progress:

- [Experiment 1: Windows Foreground Application Monitor](EXPERIMENT_01.md) is implemented as a standalone standard-library prototype. It validates hook installation, process-path resolution, classified failures, privacy-safe output, and clean shutdown. Its Win32 adapter may be reused, but it is not yet the production monitoring service.
- [Experiment 2: Entry Prompt and Window Restoration](EXPERIMENT_02.md) is implemented as a standalone prototype. It validates one-prompt-per-entry semantics, prompt self-exclusion, duplicate suppression, explicit continue behavior, re-entry prompting, and best-effort restoration of the prior work window. It does not yet include schedules, persistence, or follow-up timers.
- [Experiment 3: Complete Browser Communication Chain](EXPERIMENT_03.md) is implemented as a browser extension, stateless Native Messaging relay, per-user Named Pipe, and single-instance tray-process prototype. It validates concurrent browsers and profiles, launch races, restart and crash recovery, extension reloads, ordering, duplication, and client-side timeouts. It intentionally contains no allowlist or database behavior.
- [Experiment 4: Context Aggregator Replay Simulator](EXPERIMENT_04.md) is implemented as a deterministic, in-memory event replay. It validates request-and-epoch correlation, stale and late message rejection, per-connection deduplication and ordering, conservative multi-profile ambiguity handling, explicit `unknown` output, and the prohibition against reusing a previous domain. It has no live browser, prompt, allowlist, or database dependency.

### Phase 1: Application Allowlist Prototype

- [x] Create the system tray application.
- [ ] Implement work schedules.
- [ ] Monitor foreground-window changes.
- [ ] Resolve foreground application identities.
- [ ] Add applications from the recent-app list.
- [ ] Prompt for non-allowlisted applications.
- [ ] Record return and continue decisions.

### Phase 1 Addendum: Process Boundaries and Context Aggregation

- [x] Implement the desktop client's single-instance mutex.
- [ ] Implement the per-user Named Pipe Server and ACL.
- [ ] Implement the stateless Native Messaging Host.
- [ ] Define and test handshake, protocol versioning, and message-size limits.
- [ ] Implement heartbeat, timeout, and bounded reconnection behavior.
- [ ] Implement ContextAggregator, `foregroundEpoch`, and `contextRevision`.
- [ ] Verify Chrome, Edge, multi-window, and multi-profile snapshot correlation.
- [x] Confirm that only the tray client accesses SQLite.

### Phase 2: Timing and Reviews

- [ ] Track application foreground time.
- [ ] Implement follow-up prompts during continued use.
- [ ] Store daily activity records.
- [ ] Generate the evening review.
- [ ] Send local Windows notifications.

### Phase 3: Website Allowlist

- [ ] Create the Manifest V3 browser extension.
- [ ] Monitor active tabs and domain changes.
- [ ] Establish Native Messaging communication.
- [ ] Implement website allowlist rules.
- [ ] Track non-allowlisted website foreground time.

### Phase 4: Packaging and Testing

- [ ] Package the Windows executable.
- [ ] Test supported Windows versions and display configurations.
- [ ] Test Chrome, Edge, and Brave.
- [x] Complete migration and failure-recovery testing.
- [ ] Evaluate code signing and public distribution.
