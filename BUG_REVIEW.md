# M6 Bug Audit and Regression Fixes

Scope: current production desktop application, browser extension, Native Messaging relay, context/prompt timing, SQLite history, and daily reviews. The isolated communication experiment is retained as a regression baseline. This is a record of confirmed defects and fixes, not a claim that every possible OS/browser defect has been eliminated. M6 still requires manual acceptance; no commit or push is part of this audit.

## Confirmed and fixed

P1 means a core interaction can fail or produce an incorrect interruption. P2 covers narrower correctness or recovery defects.

| Priority | Trigger and defect | Correction and regression evidence |
| --- | --- | --- |
| P1 | Slow extension reads finish after a newer tab/window sample and publish stale context. | Sampling generations discard superseded reads, retain a pending request's correlation, and reject obsolete-port disconnects. Three deterministic JavaScript tests exercise sampling races, correlation and internal pages. |
| P1 | A delayed unsolicited snapshot from the bound profile replaces the new foreground domain. | Changed unsolicited samples now request revalidation; only the correlated response resolves the context. Same-context messages do not create revisions. Covered by aggregator and application-service tests. |
| P1 | Skipping own-process foreground events counts time spent in Lock-In against the previous target. Naively including them invalidates the prompt itself. | Monitor own windows, pause timing/accounting appropriately, and suppress browser evaluation behind the prompt. An end-to-end service test covers own focus, Continue, browser revalidation and a subsequent follow-up. |
| P1 | Website Continue cancels its timer, and follow-up validation compares the website to the application's executable key. | Arm website intervals and verify the current website key. Count only verified foreground time; pending revalidation pauses the interval. |
| P1 | A newly connected profile replays an old foreground observation, moving the active timer backwards and potentially aborting its snapshot request. | Revalidate browser context using connection receipt time without emitting an artificial old foreground event. An application-service regression verifies both the request and its timestamp. |
| P1 | Saving settings resets continued time; adding a target to the allowlist leaves an obsolete prompt or continued timer. | Preserve still-valid elapsed time, re-evaluate pending/continued targets and dismiss/cancel allowed ones. Update changed schedule metadata without recording another entry. |
| P1 | A sleeping but locked system is treated as available on wake. A cancelled shutdown leaves timing paused. | Track lock, sleep and ending-session state independently. Resume only when all permit it and wait for fresh foreground/context evidence. |
| P1 | A Host that stops reading can block the policy dispatcher on a Named Pipe write. | Use bounded per-peer outboxes and dedicated writers; disconnect an overflowing peer. Tests deliberately stall a writer and fill its queue. |
| P1 | Concurrent hello registration can race; shutdown reader/writer threads can double-close a Windows handle. | Register sessions atomically and serialize handle closure. A real production-pipe test covers two peers and server restart. Background-thread exceptions now fail pytest instead of passing as warnings. |
| P1 | A Host started just before tray Exit launches later and clears the exit marker. Marker-write failure also uses an unrecognized log code. | Distinguish Host/manual launch, recheck after mutex acquisition, preserve explicit exit, and permit safe failure logging without cancelling shutdown. Isolated test profiles do not change the real exit marker. |
| P1 | Window restoration attaches external input queues and synchronously restores an external window, risking a stalled decision dispatcher. | Use asynchronous restore and a best-effort foreground request without input attachment. Activation errors still dismiss and record the decision. Mock-adapter tests verify these guarantees; actual foreground permission remains Windows-controlled. |
| P2 | Escape closes QDialog through a path that bypasses the Continue decision. | Escape uses the same acknowledged decision path as Continue/X, with a real Qt key-event regression. Website follow-ups also use website-specific wording. |
| P2 | Short retention deletes a missed day's history before sending its catch-up; late checkpoints can resurrect deleted usage. | Persist the cutoff, reject expired writes and record an expired catch-up as skipped without using today's delivery slot. |
| P2 | Crashed sessions remain open forever and evade retention. Clock rollback can prevent session closure. | Recover interrupted sessions before opening new ones; clamp closure to the recorded start when wall time moved backwards. Never extrapolate downtime into usage. |
| P2 | Aggregator duplicate-sequence memory grows with every message and remains after disconnect. | Bound recent sequence history per connection and remove it at disconnect, retaining the high-water mark while connected. |
| P2 | Unicode allowlist names and bracketed IPv6 hostnames do not match browser hostnames consistently. | Normalize with non-transitional UTS #46 IDNA and canonical IP parsing. Regressions include Chinese domains, sharp-s, full-width input and IPv6. |
| P2 | The shared production relay enables Experiment 3's intentional crash command. | Crash injection is now opt-in only for the experiment entry point. |
| P2 | Failure during the initial SQLite PRAGMAs leaves the connection unclosed. | Include connection configuration in the cleanup-protected initialization block, with an injected-failure regression. |

## Verification

Final audit run: **155 Python tests passed**, **3 JavaScript race tests passed**, and all **6 communication-harness scenarios passed**. Formatting, lint, compilation, extension syntax, repository hygiene and documentation-link checks also passed, with no background-thread exception warnings.

After updating the source, install the declared dependencies into the project environment:

```powershell
.\.venv\Scripts\python -m pip install -e ".[dev]"
powershell -ExecutionPolicy Bypass -File .\scripts\verify.ps1 -IncludeWindowsIntegration
```

The gate runs formatting, lint, compilation, Python tests, extension syntax checks, JavaScript race regressions, repository/link checks, and the Experiment 3 subprocess communication harness. Python tests also use the **production** Named Pipe server with temporary pipe names and temporary databases; they do not alter real schedules/history or browser registrations.

The communication harness covers simultaneous startup, Chrome/Edge profile identities, duplicates, ordering, late responses, Host crashes, reconnects, tray restart and extension reload. It simulates browser-side participants; it does not replace acceptance in actual Chrome/Edge.

## Manual regression checklist

1. Exit Lock-In from the tray, install dependencies if needed, reload the production extension in each Chrome/Edge profile, then manually start `.\.venv\Scripts\lock-in.exe`. Do not run an old process against new source while validating.
2. Set a 30-second follow-up and an active work schedule. Visit an unallowlisted site, choose Continue, and remain foreground for about 35 seconds. Expect one follow-up, not an immediate duplicate. Repeat with X and Escape.
3. Rapidly alternate allowed/unallowed tabs, browser windows/profiles and a desktop work application. No prompt should name a domain from the previous window, appear after leaving the browser, or use the previous domain on an internal browser page. Uncertain state may legitimately show `unknown` with no website prompt.
4. After Continue, spend about 10 seconds in the target, 40 seconds in Lock-In settings, then return to the target. The follow-up should require about 20 more verified target seconds. Saving unrelated settings must not reset this progress. Outside-allowlist review time must not grow while Lock-In is foreground.
5. Add the continued target to the allowlist and verify it no longer gets a follow-up. Confirm a renamed active schedule does not create an extra entry count. Application Return remains available; website prompts have only Continue.
6. Lock Windows, sleep if convenient, wake while still locked, then unlock. Neither locked nor sleeping time should count. Do not expect a prompt before fresh foreground/context evidence.
7. Exit from the tray while browsers remain open and wait at least 15 seconds. Lock-In must stay closed. Manual launch must restore normal operation and reconnection.
8. Complete the review and real notification checks in [MILESTONE_06.md](MILESTONE_06.md). Do not reduce retention against real history just to test deletion; the automated tests use disposable data.

## Remaining validation boundaries

- Real Chrome/Edge multi-window timing under heavy load, real sleep/lock transitions, and notification visibility still require manual acceptance. A 300 ms correlation timeout intentionally fails open rather than reusing a stale domain.
- Application Return is best effort: Windows can deny foreground activation, or the previous window may no longer exist. The decision must still close the prompt. The removed website Return action is not reintroduced.
- A forced termination can lose the unflushed usage tail. A crash after notification reservation may leave an unconfirmed receipt that is not retried, deliberately avoiding duplicate interruptions. These are documented M6 guarantees, not exactly-once notification delivery.
- This audit is not certification of installer/update behavior, antivirus compatibility, sustained resource usage, packaged-app identity, or hostile local-peer security. Release hardening, explicit pipe-access/security verification, and installation acceptance remain separate release gates.

## Technical references

The activation change follows Microsoft's description of [ShowWindowAsync](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync) and its warning about [attaching input queues during foreground activation](https://devblogs.microsoft.com/oldnewthing/20080801-00/?p=21393). Hostname normalization uses the [idna project's UTS #46 support](https://github.com/kjd/idna).
