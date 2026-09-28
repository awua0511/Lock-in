"""Application-thread review orchestration; database callbacks only publish events."""

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, replace
from datetime import date, datetime

from lock_in.app.events import ApplicationEvent, ApplicationEventKind
from lock_in.app.logging_setup import safe_log
from lock_in.context.aggregator import ContextResolution
from lock_in.reviews.models import NotificationResult, UsageRecord
from lock_in.reviews.usage import UsageTracker
from lock_in.storage.reviews import ReviewRepository


@dataclass(frozen=True, slots=True)
class ReviewCompletion:
    operation: str
    value: object = None
    context: object = None
    error: str | None = None


class ReviewService:
    name = "reviews"

    def __init__(
        self,
        repository: ReviewRepository,
        ui,
        logger: logging.Logger,
        publish: Callable[[ApplicationEvent], bool],
        *,
        clock=None,
        monotonic=None,
        own_pid=None,
    ) -> None:
        self._repository = repository
        self._ui = ui
        self._logger = logger
        self._publish = publish
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._monotonic = monotonic or (lambda: time.monotonic_ns() // 1_000_000)
        self._usage = UsageTracker(os.getpid() if own_pid is None else own_pid)
        self._pending: dict[date, UsageRecord] = {}
        self._retry: list[UsageRecord] = []
        self._last_flush = 0
        self._next_check = 0
        self._check_pending = False
        self._available = True
        self._stopped = False
        self._request_id = 0
        self._waiting_notification = None

    def start(self) -> None:
        pass

    def stop(self, timeout: float) -> None:
        self._advance(self._clock(), self._monotonic())
        self._stopped = True
        records = self._take_usage()
        if records:
            self._repository.save_usage(records).result(timeout=timeout)

    def update_focus_configuration(self, configuration) -> None:
        self._advance(self._clock(), self._monotonic())
        self._usage.configuration = configuration
        self._next_check = 0

    def observe_foreground(self, observation) -> None:
        self._advance(self._clock(), observation.monotonic_ms)
        self._usage.observe(observation)

    def observe_website_context(self, context, hwnd: int) -> None:
        self._advance(self._clock(), self._monotonic())
        domain = None
        if (
            context is not None
            and context.resolution is ContextResolution.RESOLVED
            and context.website_evaluation_allowed
            and context.browser
        ):
            domain = context.browser.domain
        self._usage.website(domain, hwnd)

    def availability(self, available: bool, monotonic_ms: int) -> None:
        self._advance(self._clock(), monotonic_ms)
        self._available = available
        self._usage.availability(available)
        self._next_check = 0
        self._flush()
        if available and self._waiting_notification is not None:
            review = self._waiting_notification
            self._waiting_notification = None
            self._prepare_notification(review)

    def tick(self, now: datetime, monotonic_ms: int) -> None:
        if self._stopped:
            return
        self._advance(now, monotonic_ms)
        if monotonic_ms - self._last_flush >= 30_000:
            self._flush()
            self._last_flush = monotonic_ms
        if (
            self._available
            and not self._check_pending
            and monotonic_ms >= self._next_check
        ):
            self._check_pending = True
            self._next_check = monotonic_ms + 15_000
            self._submit(
                "due",
                self._repository.check_due(now, self._usage.configuration.settings),
            )

    def request(self, day: date) -> None:
        self._advance(self._clock(), self._monotonic())
        self._flush()
        self._request_id += 1
        self._submit("view", self._repository.load(day), self._request_id)

    def notification_result(self, result: NotificationResult) -> None:
        self._submit(
            "delivery", self._repository.delivery_result(result.day, result.status)
        )

    def complete(self, result: ReviewCompletion) -> None:
        if self._stopped:
            return
        if result.operation == "due":
            self._check_pending = False
        if result.error is not None:
            if result.operation == "usage":
                self._retry.extend(result.context)
            safe_log(
                self._logger,
                logging.ERROR,
                "review_operation_failed",
                operation=result.operation,
                exception_type=result.error,
            )
            self._ui.report_operation_error("review_" + result.operation)
            return
        if result.operation == "view" and result.context == self._request_id:
            self._ui.update_review(result.value)
        elif result.operation == "due" and result.value is not None:
            self._flush()
            self._submit("notify", self._repository.load(result.value.day))
        elif result.operation == "notify":
            self._prepare_notification(result.value)
        elif result.operation == "prepare" and result.value:
            if self._available:
                self._ui.show_review_notification(result.context)
            else:
                self._waiting_notification = result.context

    def _prepare_notification(self, review) -> None:
        if not self._available:
            self._waiting_notification = review
            return
        self._submit(
            "prepare",
            self._repository.prepare_delivery(review.day, self._clock()),
            review,
        )

    def _advance(self, now: datetime, monotonic_ms: int) -> None:
        for record in self._usage.advance(now, monotonic_ms):
            previous = self._pending.get(record.local_day)
            self._pending[record.local_day] = (
                record
                if previous is None
                else replace(
                    previous,
                    scheduled_ms=previous.scheduled_ms + record.scheduled_ms,
                    outside_ms=previous.outside_ms + record.outside_ms,
                )
            )

    def _take_usage(self) -> tuple[UsageRecord, ...]:
        records = (*self._retry, *self._pending.values())
        self._pending.clear()
        self._retry.clear()
        return records

    def _flush(self) -> None:
        records = self._take_usage()
        if records:
            self._submit("usage", self._repository.save_usage(records), records)

    def _submit(self, operation: str, future: Future, context=None) -> None:
        def completed(done):
            try:
                result = ReviewCompletion(operation, done.result(), context)
            except Exception as error:
                result = ReviewCompletion(
                    operation, context=context, error=type(error).__name__
                )
            self._publish(
                ApplicationEvent(
                    ApplicationEventKind.REVIEW_COMPLETED,
                    "reviews",
                    payload=result,
                )
            )

        future.add_done_callback(completed)
