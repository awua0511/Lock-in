# Lock-In

Lock-In is a local-first focus assistant for Windows. During a user-defined work period, it notices when the foreground application or website is outside the current work allowlist and presents a brief decision prompt.

Lock-In does not forcibly block software. Its purpose is to interrupt automatic avoidance and turn it into a conscious choice: return to the previous work context or continue intentionally.

> Lock-In is under active development. The four experiments and Milestones 0–6 have progressed to the final implementation stage. Milestone 7 adds an unsigned Windows test package, recoverable per-user setup, performance checks, and a redesigned UI. Final manual acceptance is still required; this is not a public release.

## Project Status

The repository currently contains four completed risk-validation experiments:

| Experiment | Validated behavior |
| --- | --- |
| [1. Foreground application monitor](EXPERIMENT_01.md) | Event-driven Win32 foreground detection, executable identity resolution, classified failures, and clean shutdown. |
| [2. Entry prompt and restoration](EXPERIMENT_02.md) | One prompt per entry, self-exclusion, duplicate suppression, continue behavior, and best-effort restoration of the prior work window. |
| [3. Browser communication chain](EXPERIMENT_03.md) | Chrome/Edge extension → Native Messaging Host → Named Pipe → single-instance tray process → acknowledgement. |
| [4. Context aggregation simulator](EXPERIMENT_04.md) | Safe correlation of Windows and browser events, including stale, late, duplicate, out-of-order, ambiguous, and timed-out messages. |

The experiments remain isolated prototypes. The application includes application/website reminders, follow-up timing, local daily reviews, and six sidebar pages for configuration and status. See [PLAN.md](PLAN.md) for the delivery sequence and [M7 acceptance](MILESTONE_07.md) for package and UI testing.

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

Applications can be added by clicking a capture button and switching to the target application. Recently observed applications and direct executable selection remain available as fallbacks. Allowlisted applications do not trigger prompts during an active work period.

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

Website prompts offer only **Continue anyway**. Closing a prompt with X or Escape also counts as Continue. Follow-up timing applies to both applications and resolved websites, and pauses while Lock-In itself is foreground.

### Evening review

The **Reviews** page shows recorded schedule time, entry prompts, follow-up prompts, decisions, non-allowlisted foreground time, and event details for a selected local date. Recorded schedule time covers observed activity while Lock-In is running; it is not planned time or proof of productive work. Overlapping schedules count once, and unknown websites are not treated as non-allowlisted.

**Settings** controls the daily notification time and history retention. Lock-In requests at most one Windows review notification per local day, including a latest missed review after restart or wake. Clicking it opens the review. Windows notification settings may hide it; the in-app review remains available. History before Milestone 6 has no reconstructed duration or local-date statistics.

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
| Windows test packaging | PyInstaller, shared onedir runtime |

The production runtime uses PySide6, SQLite from Python's standard library, `tzdata` for schedule time zones, and `idna` for international hostname normalization. Development dependencies and version ranges are declared in `pyproject.toml`.

## Windows Test Package

M7 provides a Python-free test bundle and a per-user setup tool. Extract the complete ZIP, exit any old tray instance, and launch `LockIn/lock-in.exe`. It uses your existing local settings. Browser integration requires registration for the extension ID shown in each profile.

See [package installation and manual acceptance](MILESTONE_07.md) and [measured results / remaining release gates](docs/RELEASE_VALIDATION.md). The installer can stage updates, roll back compatible schemas, and uninstall without removing user data. There is no automatic update or sign-in startup task.

## Development Setup

Requirements:

- Windows 10 or Windows 11.
- Python 3.12 or newer.
- PowerShell.
- Node.js 20 or newer for browser-extension syntax and race-regression checks.
- Chrome or Edge for website integration and browser acceptance tests.

Create the environment and install the project:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Run the complete automated test suite:

```powershell
.\.venv\Scripts\python -m pytest -v
```

Run the current desktop application:

```powershell
.\.venv\Scripts\lock-in.exe
```

The source command remains attached to PowerShell while the application runs. The status window appears on startup; closing it hides the window when the tray is available, and **Exit** in the tray menu stops the process.

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
├── app/                 Production lifecycle, event queue, and coordinator
├── communication/       Versioned protocol primitives
├── context/             ContextAggregator and immutable contexts
├── domain/              Immutable schedules, allowlists, settings, and history
├── distribution/        Validated bundles and recoverable per-user installation
├── experiments/         Standalone risk-validation programs
├── ipc/                 Production browser Named Pipe server
├── monitoring/           Production foreground-monitor lifecycle adapter
├── native_host/         Native Messaging relay and registration
├── notifications/       Reserved notification boundary
├── platform/windows/    Win32 adapters
├── prompts/             Entry-prompt policy prototype
├── reviews/             Daily review models and independent usage measurement
├── rules/               Pure schedules, application matching, and prompt policy
├── sessions/            Monotonic continued-use timing
├── storage/             SQLite migrations, worker, and typed repositories
└── ui/                  PySide6 window, tray, and thread-safe signal bridge

browser_extension/
├── experiment3/         Chrome/Edge communication experiment
└── production/          Chrome/Edge website-context extension

scenarios/               Replayable ContextAggregator event timelines
tests/                   Unit and deterministic replay tests
```

## Documentation

- [Implementation plan](PLAN.md)
- [Milestone 1 acceptance](MILESTONE_01.md)
- [Milestone 2 acceptance](MILESTONE_02.md)
- [Milestone 3 acceptance](MILESTONE_03.md)
- [Milestone 4 acceptance](MILESTONE_04.md)
- [Milestone 5 acceptance](MILESTONE_05.md)
- [Milestone 6 acceptance](MILESTONE_06.md)
- [Milestone 7 package and UI acceptance](MILESTONE_07.md)
- [Release validation results](docs/RELEASE_VALIDATION.md)
- [Bug audit, fixes, and regression checklist](BUG_REVIEW.md)
- [Technical architecture](ARCHITECTURE.en.md)
- [Validated baseline and acceptance](docs/BASELINE.md)
- [Supported platforms](docs/SUPPORT.md)
- [Architecture decision records](docs/decisions/README.md)
- [Experiment 1](EXPERIMENT_01.md)
- [Experiment 2](EXPERIMENT_02.md)
- [Experiment 3](EXPERIMENT_03.md)
- [Experiment 4](EXPERIMENT_04.md)
- [Chinese overview and installation guide](README.zh-CN.md)

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
