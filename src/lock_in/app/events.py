"""Typed events crossing production component boundaries."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ApplicationEventKind(StrEnum):
    STARTED = "started"
    SHOW_MAIN_WINDOW = "show_main_window"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    COMPONENT_FAILED = "component_failed"


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    kind: ApplicationEventKind
    source: str
    fields: tuple[tuple[str, str], ...] = ()
    monotonic_ns: int = field(default_factory=time.monotonic_ns)

    @classmethod
    def component_failed(
        cls, component: str, operation: str, error: BaseException
    ) -> ApplicationEvent:
        return cls(
            kind=ApplicationEventKind.COMPONENT_FAILED,
            source="lifecycle",
            fields=(
                ("component", component),
                ("operation", operation),
                ("exception_type", type(error).__name__),
            ),
        )

    def field(self, name: str) -> str | None:
        return dict(self.fields).get(name)
