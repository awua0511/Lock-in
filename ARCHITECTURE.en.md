# Lock-In Architecture

English | [简体中文](ARCHITECTURE.md)

This document describes the technical architecture of the Lock-In Windows client and browser extension. For product features and user-facing behavior, see [README.en.md](README.en.md).

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
┌────────────────────────────────────────┐
│             Windows Client             │
│                                        │
│  UI / Scheduling / Allowlists / Rules  │
│  Foreground Monitor / Timer / Reviews  │
└───────────────────┬────────────────────┘
                    │ Native Messaging
┌───────────────────▼────────────────────┐
│            Browser Extension           │
│                                        │
│  Tab Activation / Navigation / Domain  │
└───────────────────┬────────────────────┘
                    │
┌───────────────────▼────────────────────┐
│            Local SQLite Database       │
│                                        │
│  Schedules / Allowlists / Events       │
└────────────────────────────────────────┘
```

## Module Boundaries

The Windows client should be divided into modules similar to the following:

```text
lock_in/
├── app/                  Entry point and application lifecycle
├── ui/                   PySide6 windows, tray, and dialogs
├── monitoring/           Foreground window and browser monitoring
├── rules/                Schedule and allowlist evaluation
├── sessions/             Work sessions and foreground timing
├── notifications/        Prompts and evening notifications
├── storage/              SQLite repositories and migrations
├── native_messaging/     Browser extension communication
└── platform/windows/     Win32 API wrappers

browser_extension/
├── manifest.json
├── service-worker.js
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

The extension sends only normalized information:

```json
{
  "event": "active_url_changed",
  "browser": "edge",
  "windowId": 42,
  "tabId": 108,
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

## Native Messaging

The browser extension communicates with the local client through Native Messaging. Messages use UTF-8 JSON with the browser-required four-byte little-endian length prefix.

The Native Messaging Host must:

- Have a stable, unique application identifier.
- Declare the extension IDs permitted to connect.
- Reject unknown or malformed messages.
- Include a protocol version in the message schema.
- Enforce a maximum message size.

Recommended message envelope:

```json
{
  "protocolVersion": 1,
  "event": "active_url_changed",
  "payload": {
    "browser": "edge",
    "domain": "youtube.com"
  },
  "timestamp": "2026-09-16T13:08:00-04:00"
}
```

The client should distinguish between these browser-extension states:

- Connected with current tab data.
- Browser running but extension not connected.
- Extension connected but current page cannot be identified.
- Extension not installed.

An unknown state must not be incorrectly treated as a non-allowlisted website.

## Rules Engine

The rules engine receives a unified `ForegroundContext`:

```json
{
  "application": {
    "kind": "win32",
    "executablePath": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  },
  "website": {
    "domain": "github.com"
  },
  "observedAt": "2026-09-16T13:08:00-04:00"
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
        └── Yes → Evaluate the current domain and website allowlist
```

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
- Native Messaging thread or subprocess for browser standard input/output.
- Data-access layer with short SQLite transactions and serialized writes.

All cross-thread events pass through a unified queue before being forwarded to the UI or rules engine. WinEvent callbacks must never manipulate PySide6 widgets directly.

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

### Phase 1: Application Allowlist Prototype

- [ ] Create the system tray application.
- [ ] Implement work schedules.
- [ ] Monitor foreground-window changes.
- [ ] Resolve foreground application identities.
- [ ] Add applications from the recent-app list.
- [ ] Prompt for non-allowlisted applications.
- [ ] Record return and continue decisions.

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
- [ ] Complete migration and failure-recovery testing.
- [ ] Evaluate code signing and public distribution.

