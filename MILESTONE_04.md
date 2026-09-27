# Milestone 4: Foreground Timing and Follow-Up Prompts

Milestone 4 extends the accepted application-only loop. It does not add browser integration, website rules, daily reviews, or packaging.

## Delivered Scope

- Immutable foreground segments measured only with a monotonic clock.
- Configurable follow-up interval from 30 seconds to 24 hours.
- One follow-up prompt after each completed foreground interval.
- A new interval only after the user chooses **Continue anyway** again.
- Immediate invalidation when the tracked application context changes.
- Windows lock, unlock, suspend, resume, shutdown, and schedule-end boundaries.
- Resume requires a fresh matching foreground observation.
- Memory-only partial timing, so restart cannot invent elapsed time.
- Follow-up foreground seconds recorded with attention history.

## Automated Acceptance

Run the timing and focus-service tests:

```powershell
.\.venv\Scripts\python -m pytest `
    tests\test_foreground_timer.py `
    tests\test_system_events.py `
    tests\test_focus_application_service.py `
    tests\test_application_focus_policy.py `
    -v
```

Run the complete quality gate:

```powershell
.\scripts\verify.ps1
```

## Manual Acceptance

### 1. Prepare a short interval

Start Lock-In, create an active schedule, and leave one ordinary application outside its allowlist. In **Settings**, set **Remind again after** to `30 seconds` and save it.

### 2. Verify foreground-only timing

1. Enter the non-allowlisted application and choose **Continue anyway**.
2. Keep it foreground for 10 seconds, switch to an allowed application for at least 30 seconds, then return.
3. The return is a new entry and may show the normal entry prompt; the 30 seconds spent elsewhere must not appear as continued foreground use.
4. Choose Continue again and keep the same target foreground. One follow-up should appear after about 30 seconds.
5. Leave that prompt open for several seconds. No duplicate follow-up should stack.
6. Choose Continue again. A second follow-up should require another complete foreground interval.

### 3. Verify lock and sleep boundaries

1. Continue into the target and keep it foreground for about 10 seconds.
2. Lock Windows for at least 30 seconds, unlock, and return to the target.
3. A follow-up must not appear immediately because locked time is excluded.
4. Repeat using system sleep if the test machine supports it.

### 4. Verify schedule end and restart

1. Continue into a target near the end of a schedule. No follow-up may appear after that schedule ends.
2. Continue into a target, exit Lock-In before the threshold, wait, and restart it. The stopped interval must not be recovered or immediately trigger a follow-up.

## Acceptance Boundary

Accept Milestone 4 only when the automated gates and manual timing checks pass. Acceptance does not authorize production browser integration or Milestone 5.
