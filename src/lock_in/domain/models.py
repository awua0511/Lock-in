"""Immutable product data independent of UI, SQLite, and Windows APIs."""

from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import StrEnum


def new_id() -> str:
    return str(uuid.uuid4())


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")


class RecurrenceKind(StrEnum):
    ONCE = "once"
    WEEKLY = "weekly"


@dataclass(frozen=True, slots=True)
class Recurrence:
    kind: RecurrenceKind
    id: str = field(default_factory=new_id)
    weekday: int | None = None
    occurrence_date: date | None = None

    def __post_init__(self) -> None:
        _require_text(self.id, "recurrence id")
        if self.kind is RecurrenceKind.ONCE:
            if self.occurrence_date is None or self.weekday is not None:
                raise ValueError("one-time recurrence requires only occurrence_date")
        elif self.weekday is None or not 0 <= self.weekday <= 6:
            raise ValueError("weekly recurrence requires weekday from 0 to 6")
        elif self.occurrence_date is not None:
            raise ValueError("weekly recurrence cannot have occurrence_date")


@dataclass(frozen=True, slots=True)
class Schedule:
    name: str
    start_time: time
    end_time: time
    timezone: str
    recurrences: tuple[Recurrence, ...]
    id: str = field(default_factory=new_id)
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_text(self.id, "schedule id")
        _require_text(self.name, "schedule name")
        _require_text(self.timezone, "schedule timezone")
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("schedule times must be local wall-clock times")
        if self.start_time == self.end_time:
            raise ValueError("schedule start and end times must differ")
        if not self.recurrences:
            raise ValueError("schedule requires at least one recurrence")
        recurrence_ids = {item.id for item in self.recurrences}
        if len(recurrence_ids) != len(self.recurrences):
            raise ValueError("recurrence ids must be unique within a schedule")


class ApplicationKind(StrEnum):
    WIN32 = "win32"
    PACKAGED = "packaged"


@dataclass(frozen=True, slots=True)
class ApplicationIdentity:
    kind: ApplicationKind
    display_name: str
    executable_path: str | None = None
    package_family_name: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.display_name, "application display name")
        if self.kind is ApplicationKind.WIN32:
            if not self.executable_path or self.package_family_name is not None:
                raise ValueError("win32 identity requires only executable_path")
        elif not self.package_family_name or self.executable_path is not None:
            raise ValueError("packaged identity requires only package_family_name")


@dataclass(frozen=True, slots=True)
class ApplicationAllowlistEntry:
    identity: ApplicationIdentity
    id: str = field(default_factory=new_id)
    schedule_id: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_text(self.id, "application allowlist id")
        if self.schedule_id is not None:
            _require_text(self.schedule_id, "application allowlist schedule_id")


def normalize_domain(value: str) -> str:
    domain = value.strip().rstrip(".").lower()
    _require_text(domain, "domain")
    if "://" in domain or "/" in domain or "?" in domain or "#" in domain:
        raise ValueError("domain must be a hostname, not a URL")
    try:
        ipaddress.ip_address(domain)
        return domain
    except ValueError:
        pass
    labels = domain.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("domain is not a valid hostname")
    return domain


@dataclass(frozen=True, slots=True)
class WebsiteAllowlistEntry:
    domain: str
    id: str = field(default_factory=new_id)
    schedule_id: str | None = None
    include_subdomains: bool = True
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_text(self.id, "website allowlist id")
        if self.schedule_id is not None:
            _require_text(self.schedule_id, "website allowlist schedule_id")
        object.__setattr__(self, "domain", normalize_domain(self.domain))


@dataclass(frozen=True, slots=True)
class AppSettings:
    review_time: time = time(20, 0)
    history_retention_days: int = 90
    follow_up_seconds: int = 300

    def __post_init__(self) -> None:
        if self.review_time.tzinfo is not None:
            raise ValueError("review_time must be a local wall-clock time")
        if not 1 <= self.history_retention_days <= 3650:
            raise ValueError("history_retention_days must be between 1 and 3650")
        if not 30 <= self.follow_up_seconds <= 86_400:
            raise ValueError("follow_up_seconds must be between 30 and 86400")


@dataclass(frozen=True, slots=True)
class FocusSession:
    started_at: datetime
    schedule_id: str | None = None
    ended_at: datetime | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        _require_text(self.id, "focus session id")
        _require_aware(self.started_at, "started_at")
        if self.ended_at is not None:
            _require_aware(self.ended_at, "ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("ended_at cannot precede started_at")


class TargetType(StrEnum):
    APPLICATION = "application"
    WEBSITE = "website"


class AttentionDecision(StrEnum):
    PROMPT_SHOWN = "prompt_shown"
    RETURN = "return"
    CONTINUE = "continue"


@dataclass(frozen=True, slots=True)
class AttentionEvent:
    focus_session_id: str
    occurred_at: datetime
    target_type: TargetType
    target_key: str
    decision: AttentionDecision
    foreground_seconds: int = 0
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        _require_text(self.id, "attention event id")
        _require_text(self.focus_session_id, "focus_session_id")
        _require_text(self.target_key, "target_key")
        _require_aware(self.occurred_at, "occurred_at")
        if self.foreground_seconds < 0:
            raise ValueError("foreground_seconds cannot be negative")
