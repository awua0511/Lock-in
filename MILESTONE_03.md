# Milestone 3: Application-Only Focus Loop

Milestone 3 is the first usable product slice. It supports local Windows applications only; website rules, continued-use duration, and follow-up prompts are not part of this milestone.

## Delivered Scope

- Production lifecycle adapter around the validated WinEvent foreground monitor.
- Bounded, path-deduplicated recent-application list.
- Weekly schedules with start-inclusive, end-exclusive evaluation.
- Correct overlap and midnight-crossing behavior.
- Case-insensitive normalized Windows executable matching.
- Global or per-schedule application allowlist entries.
- PySide6 schedule and application settings tabs.
- Non-blocking advisory prompt with **Return to previous window** and **Continue anyway**.
- One prompt per entry; Continue suppresses duplicates until the user leaves and re-enters.
- Best-effort restoration of an ordinary same-privilege window.
- Local focus-session, prompt-shown, return, and continue records.
- Exclusion of Lock-In, known system shells, unresolved processes, and duplicate foreground events.

## Automated Acceptance

Run the Milestone 3 tests:

```powershell
.\.venv\Scripts\python -m pytest `
    tests\test_application_focus_policy.py `
    tests\test_focus_application_service.py `
    tests\test_foreground_monitoring_service.py `
    tests\test_prompt_dialog.py `
    -v
```

Run the complete quality gate:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

## Manual Acceptance

### 1. Create an active schedule

Start Lock-In:

```powershell
.\.venv\Scripts\lock-in.exe
```

Open the **Schedules** tab. Create a schedule that includes today and spans the current time. Wait until the Overview status reports the saved schedule.

### 2. Add a work application

Open the **Applications** tab and click **Select by switching to an app…**. Switch to the application you want to allow; Lock-In should capture it, return to the settings window, and show its executable path. Select the schedule and click **Add to allowlist**.

You can also choose a recently observed application. Browsing to an `.exe` remains available as a fallback. A simple fallback choice is Notepad:

```text
C:\Windows\System32\notepad.exe
```

Wait until the application appears in **Allowed applications**. Close the Lock-In window so it remains in the tray.

### 3. Verify application-only decisions

1. Enter the allowed application. No prompt should appear.
2. Enter an ordinary non-allowed application. Exactly one prompt should appear.
3. Choose **Continue anyway**. The application should regain focus and no immediate duplicate prompt should appear.
4. Switch to the allowed application, then re-enter the non-allowed application. A new prompt should appear.
5. Choose **Return to previous window**. Windows should restore the allowed application when foreground restrictions permit it.
6. Close the prompt with its **X** once. This is treated as **Continue anyway**, not as a hidden third choice.

Outside an active schedule, no application prompt should appear. Lock-In, Explorer, Start, unresolved elevated applications, and repeated events for one unchanged window must not create prompt loops.

### 4. Verify persistence and privacy-safe counts

Exit Lock-In from the tray, restart it, and confirm the schedule and allowlist remain. Exit again, then run:

```powershell
.\.venv\Scripts\lock-in-inspect-database.exe --include-counts
```

Expected after completing the prompt checks:

- `schedules` is at least 1;
- `application_allowlist` is at least 1;
- `focus_sessions` is at least 1;
- `attention_events` is at least 2.

The inspector prints only schema information and row counts, never executable paths or event targets.

## Acceptance Boundary

Accept Milestone 3 only when the automated gates and the manual application loop pass. Acceptance does not authorize foreground-duration accumulation, follow-up prompts, website integration, or Milestone 4.
