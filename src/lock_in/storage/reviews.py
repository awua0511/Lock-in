"""Review queries, delivery deduplication and retention on the existing DB worker."""

import sqlite3
from datetime import date, datetime, timedelta

from lock_in.domain.models import AppSettings
from lock_in.reviews.models import (
    DailyReview,
    ReviewDetail,
    ReviewNotification,
    UsageRecord,
)
from lock_in.storage.repositories import _transaction
from lock_in.storage.worker import DatabaseWorker


class ReviewRepository:
    def __init__(self, worker: DatabaseWorker) -> None:
        self._worker = worker

    def save_usage(self, records: tuple[UsageRecord, ...]):
        def operation(connection):
            with _transaction(connection):
                row = connection.execute(
                    "SELECT value FROM review_state WHERE key = 'retention_cutoff'"
                ).fetchone()
                cutoff = row[0] if row else ""
                connection.executemany(
                    "INSERT OR IGNORE INTO review_usage VALUES (?, ?, ?, ?, ?)",
                    (
                        (
                            r.id,
                            r.local_day.isoformat(),
                            r.started_at.isoformat(),
                            r.scheduled_ms,
                            r.outside_ms,
                        )
                        for r in records
                        if r.local_day.isoformat() >= cutoff
                    ),
                )

        return self._worker.submit(operation)

    def load(self, day: date):
        def operation(connection):
            key = day.isoformat()
            usage = connection.execute(
                "SELECT COALESCE(SUM(scheduled_ms), 0), "
                "COALESCE(SUM(outside_ms), 0) FROM review_usage WHERE local_day = ?",
                (key,),
            ).fetchone()
            counts = connection.execute(
                """SELECT
                COALESCE(SUM(decision = 'prompt_shown' AND prompt_kind = 'entry'), 0),
                COALESCE(SUM(decision = 'prompt_shown' AND prompt_kind = 'follow_up'), 0),
                COALESCE(SUM(decision = 'continue'), 0),
                COALESCE(SUM(decision = 'return'), 0), COUNT(*)
                FROM attention_events WHERE local_day = ?""",
                (key,),
            ).fetchone()
            rows = connection.execute(
                """SELECT local_occurred_at, target_type, target_key, decision,
                prompt_kind FROM attention_events WHERE local_day = ?
                ORDER BY occurred_at DESC, id DESC LIMIT 500""",
                (key,),
            ).fetchall()
            delivery = connection.execute(
                "SELECT reason, status FROM review_deliveries WHERE local_day = ?",
                (key,),
            ).fetchone()
            return DailyReview(
                day,
                *usage,
                *counts,
                tuple(ReviewDetail(*row) for row in rows),
                f"{delivery[0]}: {delivery[1]}" if delivery else "Not requested",
            )

        return self._worker.submit(operation)

    def check_due(self, now: datetime, settings: AppSettings):
        """Reserve before UI dispatch: a crash must never cause duplicate delivery."""

        def operation(connection):
            with _transaction(connection):
                state = dict(connection.execute("SELECT key, value FROM review_state"))
                previous = (
                    datetime.fromisoformat(state["last_check"])
                    if "last_check" in state
                    else None
                )
                state["last_check"] = now.isoformat()
                zone = f"{now.tzname()}|{now.utcoffset()}"
                if state.get("zone") not in {None, zone}:
                    state["last_clock_change"] = (
                        f"{now.isoformat()}: {state['zone']} -> {zone}; "
                        "stored local dates retained; one latest review eligible"
                    )
                state["zone"] = zone
                cleanup_key = f"{now.date()}|{settings.history_retention_days}"
                cutoff = now.date() - timedelta(
                    days=settings.history_retention_days - 1
                )
                if state.get("cleanup") != cleanup_key:
                    _prune(connection, cutoff.isoformat())
                    state["cleanup"] = cleanup_key
                    state["retention_cutoff"] = cutoff.isoformat()

                candidate = None
                reason = "scheduled"
                if now.time().replace(tzinfo=None) >= settings.review_time:
                    candidate = now.date()
                    if previous is None or (now - previous).total_seconds() > 60:
                        reason = "catch_up"
                elif previous is not None and previous.date() < now.date():
                    candidate = now.date() - timedelta(days=1)
                    reason = "catch_up"

                if previous is not None and now.date() < previous.date():
                    state["last_clock_change"] = (
                        f"{now.isoformat()}: local date moved backwards; "
                        "delivery ledger prevents repeated dates"
                    )
                if candidate is not None and previous is not None:
                    first_missed = previous.date()
                    if previous.time().replace(tzinfo=None) >= settings.review_time:
                        first_missed += timedelta(days=1)
                    if first_missed < candidate:
                        state["last_coalesced_gap"] = (
                            f"{first_missed} through {candidate - timedelta(days=1)}: "
                            "missed reviews coalesced into one latest review"
                        )
                connection.executemany(
                    "INSERT OR REPLACE INTO review_state VALUES (?, ?)", state.items()
                )
                if candidate is None:
                    return None
                if candidate < cutoff:
                    connection.execute(
                        "INSERT OR IGNORE INTO review_deliveries VALUES (?, ?, ?, ?, NULL)",
                        (
                            candidate.isoformat(),
                            now.isoformat(),
                            "expired_history",
                            "skipped",
                        ),
                    )
                    return None
                day_used = (
                    connection.execute(
                        "SELECT 1 FROM review_deliveries WHERE delivery_day = ?",
                        (now.date().isoformat(),),
                    ).fetchone()
                    is not None
                )
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO review_deliveries VALUES (?, ?, ?, ?, ?)",
                    (
                        candidate.isoformat(),
                        now.isoformat(),
                        "daily_delivery_limit" if day_used else reason,
                        "skipped" if day_used else "reserved",
                        None if day_used else now.date().isoformat(),
                    ),
                ).rowcount
                return (
                    ReviewNotification(candidate, reason)
                    if inserted and not day_used
                    else None
                )

        return self._worker.submit(operation)

    def delivery_result(self, day: date, status: str):
        if status not in {"submitted_to_windows", "unavailable", "failed"}:
            raise ValueError("invalid notification delivery status")
        return self._worker.submit(
            lambda connection: (
                connection.execute(
                    "UPDATE review_deliveries SET status = ? WHERE local_day = ?",
                    (status, day.isoformat()),
                ).rowcount
            )
        )

    def prepare_delivery(self, day: date, now: datetime):
        """Recheck the delivery date after a sleep/lock during asynchronous loading."""

        def operation(connection):
            with _transaction(connection):
                row = connection.execute(
                    "SELECT status FROM review_deliveries WHERE local_day = ?",
                    (day.isoformat(),),
                ).fetchone()
                if row is None or row[0] != "reserved":
                    return False
                other = connection.execute(
                    "SELECT 1 FROM review_deliveries WHERE delivery_day = ? AND local_day != ?",
                    (now.date().isoformat(), day.isoformat()),
                ).fetchone()
                if other is not None:
                    connection.execute(
                        "UPDATE review_deliveries SET status = 'skipped', reason = 'daily_delivery_limit' WHERE local_day = ?",
                        (day.isoformat(),),
                    )
                    return False
                connection.execute(
                    "UPDATE review_deliveries SET delivery_day = ? WHERE local_day = ?",
                    (now.date().isoformat(), day.isoformat()),
                )
                return True

        return self._worker.submit(operation)


def _prune(connection: sqlite3.Connection, cutoff: str) -> None:
    connection.execute(
        "DELETE FROM attention_events WHERE COALESCE(local_day, substr(occurred_at, 1, 10)) < ?",
        (cutoff,),
    )
    connection.execute("DELETE FROM review_usage WHERE local_day < ?", (cutoff,))
    connection.execute(
        """DELETE FROM focus_sessions
        WHERE ended_at IS NOT NULL AND substr(ended_at, 1, 10) < ?
        AND NOT EXISTS (SELECT 1 FROM attention_events WHERE focus_session_id = focus_sessions.id)""",
        (cutoff,),
    )
