# Milestone 6: Reviews and Local Notifications

M6 adds local daily reviews, one daily Windows notification attempt, and configurable retention. It is awaiting user acceptance. It does not add packaging or release distribution.

## Delivered behavior

- **Reviews** has a date selector, refresh action, summary, and the latest 500 event details. Summary counts cover every event for that date.
- **Settings** exposes review time in the current local clock and retention from 1 to 3650 days. The default is 20:00 and 90 days.
- Recorded schedule time is measured while Lock-In is running, Windows is available, and a foreground observation has arrived. Overlapping schedules count once. This is neither the full planned duration nor a productivity score.
- Non-allowlisted foreground time is measured independently of Continue/follow-up counters, including time before a decision when the target is actually foreground. Lock-In's prompt/settings windows, unknown websites, unresolved processes and exempt system windows do not contribute to that total.
- Entry prompts and follow-ups are counted separately. Continue and application Return are separate decision counts. Website prompts still offer only Continue; X and Escape are also Continue.
- Durations use a monotonic clock. Midnight boundaries are split. Sleep/lock and unverified event gaps longer than five seconds are excluded. Resume requires a fresh foreground observation.
- Usage is checkpointed approximately every 30 seconds and flushed on review refresh, system suspension and clean shutdown. A forced crash can lose the unflushed tail; restart never invents elapsed time.
- Events retain their original local date and offset. Changing time zones does not reassign old events to a different date.
- Notification checks run approximately every 15 seconds. At most one attempt is made for a report date and at most one attempt is made on a delivery date. A morning catch-up uses that day's slot, so there is no second notification that evening.
- Multiple missed days are coalesced into the latest eligible day; skipped ranges and clock/zone changes have persistent reasons. Older daily views remain available subject to retention.
- The delivery ledger is written before dispatch. A crash between reservation and submission can leave `reserved` (unconfirmed), and it is not retried automatically. Windows provides no receipt that proves a banner was visible; `submitted_to_windows` means only submitted, while `unavailable` covers a missing tray/notification service.
- The app does not wake Windows or run when explicitly exited. Catch-up happens after a later manual launch. Clicking a notification opens its report date.

## Storage and compatibility

Migration 3 adds `review_usage`, `review_deliveries`, `review_state`, and local-date/prompt-kind metadata to attention events. Existing configuration and history are preserved, and the existing migration backup is created before upgrading. Older events remain in storage but are excluded from new local-day aggregates because their original local dates and entry/follow-up provenance cannot be reconstructed reliably.

Retention removes old attention events and usage, plus old closed sessions without remaining events. Active sessions and configuration are preserved. Lowering retention permanently removes expired history at the next available cleanup check. Tiny notification date/status receipts remain so history cleanup, manual history clearing, and clock rollback cannot cause repeat notifications. They contain no app paths or domains.

Already-expired catch-up dates are marked `expired_history: skipped` without consuming today's notification slot. Late usage retries cannot recreate expired data. Sessions left open after an interrupted process are closed conservatively at startup before new sessions begin; no downtime is added to usage totals.

## Automated acceptance

From the repository root:

```powershell
.\scripts\verify.ps1
```

Focused tests:

```powershell
.\.venv\Scripts\python -m pytest tests/test_daily_reviews.py tests/test_review_ui.py tests/test_storage_migrations.py tests/test_application_process.py
```

These cover deterministic aggregation, overlapping schedules, midnight and clock changes, unknown/allowed domains, lock/resume, stale UI results, failed-write retries, repeated notification checks and process restart, delivery-date limits, retention boundaries, upgrade rollback, notification submission status, and the real desktop application's startup/shutdown path with temporary data.

## Manual acceptance

### 1. Start and configure

Exit the existing Lock-In instance through its tray menu, then run:

```powershell
.\.venv\Scripts\lock-in.exe
```

Confirm existing schedules and allowlists remain. In **Settings**, set the follow-up interval to 30 seconds, choose a daily review time, and keep the normal retention setting while testing with real history. Save, restart, and confirm all three settings persist.

### 2. Verify the daily review

1. Create an active schedule. Open a non-allowlisted application, choose Continue, and leave it foreground for around 35 seconds.
2. Choose Continue on the follow-up. Switch to an allowed application for around 10 seconds.
3. Open **Reviews**, select today and refresh. There should be an entry prompt, a separate follow-up, and their Continue decisions. The two decision records must not double the recorded foreground duration.
4. During an active schedule, visit a resolved unallowed website. Its prompt must offer only Continue. Choose Continue, stay for around 35 foreground seconds, and confirm one follow-up. Close it with Escape and verify no immediate repeat. Switch away, then refresh Reviews and check separate entry/follow-up records and the increased outside-allowlist duration.
5. Stay in the Reviews tab for 10 seconds and refresh. Recorded schedule time can increase; outside-allowlist time must not increase while Lock-In itself is foreground.
6. Select a day without M6 data. It should show zero records rather than today's data. Restart and re-open today's review; persisted totals and decisions should remain.

### 3. Verify time boundaries

1. Continue in a non-allowlisted target, then lock Windows for at least 30 seconds. Unlock and switch to a work application before refreshing the review. Locked time must not increase either duration total.
2. Repeat with sleep/resume when supported. A missed notification should wait until Windows is available.
3. Use two overlapping schedules. Recorded schedule time must grow at approximately one second per elapsed second, not two.
4. Let a schedule end. Usage after the boundary must not count toward the schedule or outside-allowlist totals.

### 4. Verify notification delivery

1. On a local date when no review has yet been attempted, set the review time one or two minutes ahead. Keep Lock-In running with its tray icon visible.
2. Around that time (allow 15 seconds), confirm at most one Windows notification. Click it and verify **Reviews** opens on the report date.
3. Restart Lock-In and change the configured review time to a time earlier today. Neither action may send the same day's review again.
4. For catch-up, on a different unused delivery day, exit before the configured time and launch afterward. Expect a single latest review, not one notification for every missed day. A catch-up earlier in the day also suppresses that evening's second attempt.
5. If Windows Do Not Disturb hides the banner, open Reviews and refresh: `submitted_to_windows` is expected, not proof of visible delivery. Do not delete the real database or change the system date just to bypass the daily limit; deterministic tests cover repeat and missed-day scenarios.

### 5. Retention

Use automated tests or a disposable profile when testing destructive expiry. With real history, lower retention only if you intend to remove it. Confirm schedules, website/application allowlists and settings persist after cleanup and restart.

## Acceptance boundary

Accept M6 only after the automated checks and manual review/notification checks pass. Record Windows notification suppression separately from application delivery failure. M7 and any commit/push remain gated on user acceptance.

The cross-module regression fixes and a short additional manual checklist are recorded in [BUG_REVIEW.md](BUG_REVIEW.md).
