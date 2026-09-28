# ADR 0007: Local daily reviews and notification receipts

Status: Implemented; pending Milestone 6 acceptance.

## Context

Reminder history stores a duration on both a follow-up prompt and its decision. Summing those fields double-counts time, omits use shorter than a reminder interval, and cannot establish local dates for old UTC-only records. Windows tray notifications have no reliable acknowledgement of visible delivery.

## Decision

`UsageTracker` measures independent monotonic increments during active schedules. One tracker accounts for overlapping schedules once. It receives foreground observations and only correlated website contexts; unknown sites never become outside-allowlist duration. Lock-In windows are excluded from outside time. Locks, sleep, missing fresh foreground after resume, and unverified gaps over five seconds do not accrue time. Duration records are grouped by their original local date and checkpointed every 30 seconds, on requested review, on suspension and on clean shutdown.

`ReviewService` owns review state on the serialized application event thread. Database callbacks publish typed completion events; UI work travels through Qt signals. Summaries and up to 500 recent details come from the sole SQLite worker. Each view request has a generation to prevent an old date's result replacing a newer request.

Migration 3 retains original local date/offset and prompt kind for new attention records. Legacy records are preserved without fabricating missing provenance. Recorded schedule time means observed coverage while the app runs, not all planned time, attention, or productivity.

Notification reservation precedes UI submission, with unique report and delivery dates. Catch-up chooses one latest eligible date and consumes the current day's slot. A reservation is rechecked if loading overlaps lock/sleep and delivery resumes on a different date. Coalescing, zone changes and daily-limit skips have persisted reasons. Failed or interrupted attempts are not automatically retried; this favors no duplicate interruption over guaranteed banner delivery. Windows suppression cannot be distinguished from visible delivery, so the recorded status is `submitted_to_windows`.

Retention deletes expired usage/events and eligible closed sessions, preserving live sessions and configuration. Delivery date/status receipts contain no app/domain data and survive history clearing to enforce deduplication even after clock rollback.

Expired catch-up candidates are explicitly skipped without occupying today's delivery slot. Persisted retention cutoffs also apply to late usage retries. Interrupted sessions are closed at their recorded start time during startup, before configuration creates new sessions, so retention can reclaim them without attributing shutdown downtime to work.

## Consequences

The report is reproducible from stored records and makes its coverage limits visible. Forced termination may lose up to the unflushed 30-second tail; shutdown downtime is never extrapolated. Daily report totals for pre-M6 history are unavailable. A crash after reservation can skip one notification, while the review itself remains accessible. No scheduler process, startup registration or cloud service is introduced.
