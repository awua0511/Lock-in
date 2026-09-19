# Milestone 1: Formal Application Skeleton

Milestone 1 turns the validated experiments into a production application shell without adding schedules, allowlists, SQLite, monitoring, or production browser IPC.

## Delivered Scope

- `lock-in.exe` production entry point.
- PySide6 event loop, visible startup window, and system tray menu with **Open** and **Exit**.
- A production-specific, per-user Windows mutex that permits only one running tray instance.
- Immutable typed application events and one serialized dispatcher queue.
- A framework-independent `ApplicationCoordinator` and a Qt signal bridge. Worker events emit signals instead of manipulating widgets.
- Ordered component startup and reverse-order, idempotent shutdown with failure isolation.
- Size-bounded rotating logs with stable event codes and an allowlist of metadata fields.
- Empty package boundaries for monitoring, IPC, rules, sessions, notifications, and storage so later milestones can be added without moving ownership.

The production skeleton does not open a Named Pipe or launch a Native Messaging Host. Consequently, exiting it has no production Pipe or child Host to leave behind. Experiment 3 remains independently runnable and unchanged.

## Automated Acceptance

Install or refresh dependencies and entry points:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Run the repository quality gate:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

The suite verifies:

- synthetic event delivery on one dispatcher thread;
- Qt signal delivery on the Qt application thread;
- component failure isolation and reverse shutdown ordering;
- rejection of arbitrary sensitive log fields;
- duplicate process rejection and mutex release after shutdown;
- every earlier experiment and replay test.

## Manual Acceptance

### 1. Start and open the UI

From PowerShell, run:

```powershell
.\.venv\Scripts\lock-in.exe
```

Expected result:

- the Lock-In status window appears immediately, so startup is never silent;
- one Lock-In icon appears in the Windows notification area (possibly under the overflow arrow);
- right-clicking it shows **Open** and **Exit**;
- **Open** shows a small window stating that schedules and allowlists arrive later;
- closing the window hides it while the tray process continues.

The PowerShell command remains occupied while Lock-In is running; this is a normal source-development launch, not a frozen prompt. If Windows reports no available system tray, closing the visible window exits instead of leaving an inaccessible background process.

### 2. Verify the single-instance boundary

Keep the first instance running. In a second PowerShell window, run the same command:

```powershell
.\.venv\Scripts\lock-in.exe
```

Expected result: the second command exits promptly, and Windows still shows exactly one Lock-In tray icon and one running `lock-in.exe` process.

### 3. Verify clean shutdown and restart

Choose **Exit** from the tray menu. Then run:

```powershell
Get-Process -Name "lock-in" -ErrorAction SilentlyContinue
.\.venv\Scripts\lock-in.exe
```

Expected result: the first command prints no remaining process. The next launch succeeds and creates one tray icon, proving the mutex was released. Choose **Exit** again when finished.

### 4. Inspect the privacy-safe log

Run:

```powershell
Get-Content "$env:LOCALAPPDATA\LockIn\Logs\lock-in.log" -Tail 30
```

Expected result: records contain stable codes such as `application_started`, `application_event`, `duplicate_start_rejected`, and `application_stopped`. They contain no window titles, executable paths, URLs, page content, or user input.

## Acceptance Boundary

Accept this milestone only if all four manual checks and the automated quality gate pass. Acceptance authorizes the Milestone 1 commit and push; it does not authorize Milestone 2 implementation.
