"""Pure monotonic timing for a user-approved non-allowlisted target."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ForegroundSegment:
    target_key: tuple[int, str]
    started_ms: int
    ended_ms: int

    def __post_init__(self) -> None:
        if self.started_ms < 0 or self.ended_ms < self.started_ms:
            raise ValueError("invalid monotonic segment bounds")

    @property
    def duration_ms(self) -> int:
        return self.ended_ms - self.started_ms


@dataclass(frozen=True, slots=True)
class FollowUpDue:
    target_key: tuple[int, str]
    foreground_ms: int


class ContinuedUseTimer:
    """Accumulate only verified foreground segments for one continued target."""

    def __init__(self, threshold_seconds: int = 300) -> None:
        self._threshold_ms = 0
        self.set_threshold(threshold_seconds)
        self._target_key: tuple[int, str] | None = None
        self._accumulated_ms = 0
        self._segment_started_ms: int | None = None
        self._suspended = False

    @property
    def target_key(self) -> tuple[int, str] | None:
        return self._target_key

    @property
    def foreground_ms(self) -> int:
        return self._accumulated_ms

    def set_threshold(self, seconds: int) -> None:
        if not 30 <= seconds <= 86_400:
            raise ValueError("threshold must be between 30 and 86400 seconds")
        self._threshold_ms = seconds * 1000

    def arm(self, target_key: tuple[int, str]) -> None:
        self._target_key = target_key
        self._accumulated_ms = 0
        self._segment_started_ms = None
        self._suspended = False

    def observe(
        self, target_key: tuple[int, str] | None, monotonic_ms: int
    ) -> ForegroundSegment | None:
        self._validate_clock(monotonic_ms)
        if self._target_key is None or self._suspended:
            return None
        if target_key != self._target_key:
            segment = self._close_segment(monotonic_ms)
            self.cancel()
            return segment
        if self._segment_started_ms is None:
            self._segment_started_ms = monotonic_ms
        return None

    def tick(self, monotonic_ms: int) -> FollowUpDue | None:
        self._validate_clock(monotonic_ms)
        if self._target_key is None or self._segment_started_ms is None:
            return None
        elapsed = self._accumulated_ms + monotonic_ms - self._segment_started_ms
        if elapsed < self._threshold_ms:
            return None
        self._accumulated_ms = elapsed
        self._segment_started_ms = None
        return FollowUpDue(self._target_key, elapsed)

    def suspend(self, monotonic_ms: int) -> ForegroundSegment | None:
        self._validate_clock(monotonic_ms)
        segment = self._close_segment(monotonic_ms)
        self._suspended = True
        return segment

    def resume(self) -> None:
        if not self._suspended:
            return
        self._suspended = False
        self._segment_started_ms = None

    def cancel(self) -> None:
        self._target_key = None
        self._accumulated_ms = 0
        self._segment_started_ms = None
        self._suspended = False

    def _close_segment(self, monotonic_ms: int) -> ForegroundSegment | None:
        if self._target_key is None or self._segment_started_ms is None:
            return None
        segment = ForegroundSegment(
            self._target_key,
            self._segment_started_ms,
            monotonic_ms,
        )
        self._accumulated_ms += segment.duration_ms
        self._segment_started_ms = None
        return segment

    def _validate_clock(self, monotonic_ms: int) -> None:
        if monotonic_ms < 0:
            raise ValueError("monotonic_ms cannot be negative")
        if (
            self._segment_started_ms is not None
            and monotonic_ms < self._segment_started_ms
        ):
            raise ValueError("monotonic clock moved backwards")
