# Lock-In

Lock-In is a local-first focus assistant for Windows. During a user-defined work period, it notices when the foreground application or website is outside the current work allowlist and presents a brief decision prompt.

Lock-In does not forcibly block software. Its purpose is to interrupt automatic avoidance and turn it into a conscious choice: return to the previous work context or continue intentionally.

> Lock-In is under active development. The four highest-risk technical assumptions have been validated; the production application structure is the next milestone.

## Project Status

The repository currently contains four completed risk-validation experiments:

| Experiment | Validated behavior |
| --- | --- |
| [1. Foreground application monitor](EXPERIMENT_01.md) | Event-driven Win32 foreground detection, executable identity resolution, classified failures, and clean shutdown. |
| [2. Entry prompt and restoration](EXPERIMENT_02.md) | One prompt per entry, self-exclusion, duplicate suppression, continue behavior, and best-effort restoration of the prior work window. |
| [3. Browser communication chain](EXPERIMENT_03.md) | Chrome/Edge extension → Native Messaging Host → Named Pipe → single-instance tray process → acknowledgement. |
| [4. Context aggregation simulator](EXPERIMENT_04.md) | Safe correlation of Windows and browser events, including stale, late, duplicate, out-of-order, ambiguous, and timed-out messages. |

The experiments are intentionally isolated prototypes. They are validated building blocks, not yet a packaged end-user application. See [PLAN.md](PLAN.md) for the production implementation sequence.

## Product Principles

- Do not forcibly close or block applications and websites.
- Do not use entertainment, points, streaks, or shame as motivation.
- Always leave the final decision with the user.
- Present objective behavior reviews rather than moral judgments.
- Keep settings and activity records local by default.
- Fail open: monitoring or communication failures must never prevent normal computer use.

## Planned First Release

### Work schedules

Users create one-time or weekly recurring work periods. Each schedule selects the application and website allowlists that are active during that period.

### Application allowlist

Applications can be added from recently observed foreground applications or by selecting a local executable. Allowlisted applications do not trigger prompts during an active work period.

### Website allowlist

A Chromium extension reports only normalized browser context needed for domain matching. Lock-In does not read page content, form values, passwords, or keyboard input.

### Decision prompts

Entering non-allowlisted content presents a choice:

```text
This application is outside your current work allowlist.

Currently open: Steam
Work period: 13:00–13:40

[Return to previous window]  [Continue anyway]
```

Choosing to continue does not cancel the work period or apply a penalty. Leaving and later re-entering the target creates a new prompt. Continued foreground use can trigger a configurable follow-up prompt.

### Evening review

A local daily review summarizes scheduled work time, non-allowlisted entries, return/continue decisions, and non-allowlisted foreground time. It reports facts without judging the user's choices.

## Architecture

```text
WinEvent monitor ─┐
                  ├→ Unified event queue → ContextAggregator → Rules engine
Browser extension ┘                                      │
                                                        ├→ Prompt and timing
                                                        └→ Local persistence
```

The Windows tray client is the single owner of rule state and SQLite. Browser extensions communicate through short-lived, stateless Native Messaging Hosts and a per-user Named Pipe. Rules consume immutable contexts emitted by `ContextAggregator`; they never read Win32 or extension state directly.

See [ARCHITECTURE.en.md](ARCHITECTURE.en.md) for process boundaries, message contracts, correlation rules, threading, privacy, and failure behavior.

## Technology

| Component | Technology |
| --- | --- |
| Windows client | Python 3.12+ |
| Production desktop UI | PySide6 |
| Windows integration | `ctypes` / Win32 APIs |
| Local persistence | SQLite |
| Browser extension | Manifest V3 + JavaScript/TypeScript |
| Local browser IPC | Native Messaging + Windows Named Pipe |
| Packaging candidates | PyInstaller or Nuitka |

The current experiments use only Python's standard library where practical. PySide6 and production storage dependencies will be introduced through the formal application milestones rather than mixed into the prototypes.

## Development Setup

Requirements:

- Windows 10 or Windows 11.
- Python 3.12 or newer.
- PowerShell.
- Node.js 20 or newer for browser-extension syntax checks.
- Chrome or Edge only when running the browser experiment.

Create the environment and install the project:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Run the complete automated test suite:

```powershell
.\.venv\Scripts\python -m pytest -v
```

Run the complete baseline quality gate:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

Replay the required context-correlation scenario:

```powershell
.\.venv\Scripts\lock-in-context-replay.exe `
    scenarios\experiment_04_required.json `
    --pretty
```

Run the browser communication subprocess harness:

```powershell
.\.venv\Scripts\lock-in-communication-harness.exe
```

Windows Named Pipe integration tests may require execution outside a restricted sandbox.

## Repository Guide

```text
src/lock_in/
├── communication/       Versioned protocol primitives
├── context/             ContextAggregator and immutable contexts
├── experiments/         Standalone risk-validation programs
├── native_host/         Native Messaging relay and registration
├── platform/windows/    Win32 adapters
└── prompts/             Entry-prompt policy prototype

browser_extension/
└── experiment3/         Chrome/Edge communication extension

scenarios/               Replayable ContextAggregator event timelines
tests/                   Unit and deterministic replay tests
```

## Documentation

- [Implementation plan](PLAN.md)
- [Technical architecture](ARCHITECTURE.en.md)
- [Validated baseline and acceptance](docs/BASELINE.md)
- [Supported platforms](docs/SUPPORT.md)
- [Architecture decision records](docs/decisions/README.md)
- [Experiment 1](EXPERIMENT_01.md)
- [Experiment 2](EXPERIMENT_02.md)
- [Experiment 3](EXPERIMENT_03.md)
- [Experiment 4](EXPERIMENT_04.md)
- [Archived Chinese overview](README.zh-CN.md)

## Privacy Boundaries

- No account or cloud service is required by default.
- Complete URLs and browsing history are not uploaded.
- Website decisions use normalized domains only.
- Page content, form values, passwords, and keyboard input are never recorded.
- Window titles are excluded by default because they may contain sensitive information.
- Users will be able to delete local behavior history independently of active settings.

## Not Planned for the First Release

- Forced blocking or anti-circumvention controls.
- Cloud accounts or cross-device synchronization.
- iOS or macOS integration.
- Rewards, points, leaderboards, or streaks.
- AI judgments about whether the user is genuinely working.
- Enterprise administrator controls.

## License

No open-source license has been selected yet. Until a license is added, the repository should not be treated as granting permission to redistribute or reuse the code.
