"""Immutable review results and measured usage, independent of UI and storage."""

from dataclasses import dataclass, field
from datetime import date, datetime

from lock_in.domain.models import new_id


@dataclass(frozen=True, slots=True)
class UsageRecord:
    local_day: date
    started_at: datetime
    scheduled_ms: int
    outside_ms: int
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.started_at.utcoffset() is None:
            raise ValueError("usage timestamp must be offset-aware")
        if not 0 <= self.outside_ms <= self.scheduled_ms or self.scheduled_ms <= 0:
            raise ValueError("invalid usage duration")


@dataclass(frozen=True, slots=True)
class ReviewDetail:
    occurred_at: str
    target_type: str
    target_key: str
    decision: str
    prompt_kind: str


@dataclass(frozen=True, slots=True)
class DailyReview:
    day: date
    scheduled_ms: int
    outside_ms: int
    entries: int
    follow_ups: int
    continues: int
    returns: int
    event_count: int
    details: tuple[ReviewDetail, ...]
    delivery_status: str = "Not requested"

    @property
    def summary(self) -> str:
        return (
            f"{self.scheduled_ms // 60000} min recorded during schedules; "
            f"{self.outside_ms // 60000} min outside the allowlist. "
            f"{self.entries} entry prompts; {self.continues} Continue decisions."
        )


@dataclass(frozen=True, slots=True)
class ReviewNotification:
    day: date
    reason: str


@dataclass(frozen=True, slots=True)
class NotificationResult:
    day: date
    status: str
