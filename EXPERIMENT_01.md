# Experiment 1: Windows Foreground Application Monitor

This experiment validates that Lock-In can observe foreground-window changes and resolve them to local executable identities without polling or administrator privileges.

## Captured Fields

Each observation contains:

- Local timestamp with UTC offset.
- Monotonic timestamp in milliseconds.
- Event sequence number.
- Window handle (`HWND`).
- Process ID.
- Executable-derived application name.
- Full executable path when accessible.
- A stable resolution status.
- Win32 error details when resolution fails.

Window titles are disabled by default because they may contain document names, private messages, or other sensitive information.

## Run from Source

Create a virtual environment and install the project in editable mode:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Print the current foreground application once:

```powershell
.venv\Scripts\lock-in-foreground-monitor --once
```

Monitor foreground changes until `Ctrl+C`:

```powershell
.venv\Scripts\lock-in-foreground-monitor
```

Emit newline-delimited JSON for analysis:

```powershell
.venv\Scripts\lock-in-foreground-monitor --json
```

Run a bounded smoke test:

```powershell
.venv\Scripts\lock-in-foreground-monitor --json --duration 10
```

Window titles can be enabled explicitly for local diagnostics:

```powershell
.venv\Scripts\lock-in-foreground-monitor --include-window-title
```

Do not share captures containing window titles without reviewing them first.

## Resolution Statuses

| Status | Meaning |
| --- | --- |
| `identified` | The executable path was resolved successfully. |
| `no_foreground_window` | Windows reported no foreground window. |
| `invalid_window` | The window disappeared before resolution. |
| `window_without_process` | No owning process could be obtained. |
| `process_access_denied` | Windows denied access to the process. |
| `process_exited` | The process exited during resolution. |
| `path_query_failed` | The executable path could not be queried for another reason. |
| `callback_error` | An unexpected resolver or callback error occurred. |

Failures are emitted as observations instead of terminating the monitor. This allows the experiment to measure real-world identification coverage.

## Validation Checklist

Run the monitor and switch between:

- Standard Win32 applications.
- File Explorer.
- Microsoft Store or packaged applications.
- Chrome, Edge, and Brave.
- Task Manager.
- An elevated application.
- Full-screen applications.
- Applications on different monitors.

Also test locking and unlocking, sleep and resume, rapid switching, and closing an application immediately after activating it.

The experiment succeeds when normal applications are consistently identified, failures are classified without crashing, and CPU usage remains effectively idle between foreground changes.

## Tests

```powershell
.venv\Scripts\python -m pytest
```

Automated tests exercise resolution outcomes and output formatting without live Win32 windows. Real foreground behavior remains a Windows integration test and must be validated with the checklist above.
