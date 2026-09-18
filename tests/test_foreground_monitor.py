from __future__ import annotations

import json

import pytest

from lock_in.platform.windows.foreground_monitor import (
    ForegroundObservation,
    ForegroundResolver,
    ResolutionStatus,
    Win32ResolutionError,
    application_name_from_path,
    format_observation,
)


def fixed_clock() -> tuple[str, int]:
    return "2026-09-17T10:00:00.000-04:00", 123_456


class FakeApi:
    def __init__(
        self,
        *,
        valid: bool = True,
        pid: int = 42,
        path: str = r"C:\Program Files\Example\Example.exe",
        title: str | None = "Sensitive document title",
        error: Win32ResolutionError | None = None,
    ) -> None:
        self.valid = valid
        self.pid = pid
        self.path = path
        self.title = title
        self.error = error

    def get_foreground_window(self) -> int:
        return 100

    def is_window(self, hwnd: int) -> bool:
        return self.valid

    def get_window_process_id(self, hwnd: int) -> int:
        return self.pid

    def query_process_image_path(self, pid: int) -> str:
        if self.error is not None:
            raise self.error
        return self.path

    def get_window_title(self, hwnd: int) -> str | None:
        return self.title


def test_resolves_application_without_collecting_title_by_default() -> None:
    resolver = ForegroundResolver(FakeApi(), clock=fixed_clock)

    result = resolver.resolve(100, sequence=7)

    assert result.status == ResolutionStatus.IDENTIFIED
    assert result.sequence == 7
    assert result.hwnd == 100
    assert result.pid == 42
    assert result.application_name == "Example"
    assert result.executable_path == r"C:\Program Files\Example\Example.exe"
    assert result.window_title is None


def test_window_title_is_opt_in() -> None:
    resolver = ForegroundResolver(
        FakeApi(),
        include_window_title=True,
        clock=fixed_clock,
    )

    result = resolver.resolve(100, sequence=1)

    assert result.window_title == "Sensitive document title"


@pytest.mark.parametrize(
    ("hwnd", "api", "expected"),
    [
        (0, FakeApi(), ResolutionStatus.NO_FOREGROUND_WINDOW),
        (100, FakeApi(valid=False), ResolutionStatus.INVALID_WINDOW),
        (100, FakeApi(pid=0), ResolutionStatus.WINDOW_WITHOUT_PROCESS),
    ],
)
def test_resolver_reports_non_identifiable_windows(hwnd, api, expected) -> None:
    result = ForegroundResolver(api, clock=fixed_clock).resolve(hwnd, sequence=1)

    assert result.status == expected
    assert result.executable_path is None


def test_preserves_native_error_status_and_code() -> None:
    api = FakeApi(
        error=Win32ResolutionError(
            ResolutionStatus.PROCESS_ACCESS_DENIED,
            "access denied",
            5,
        )
    )

    result = ForegroundResolver(api, clock=fixed_clock).resolve(100, sequence=1)

    assert result.status == ResolutionStatus.PROCESS_ACCESS_DENIED
    assert result.error_code == 5
    assert result.error_message == "access denied"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Windows\System32\notepad.exe", "notepad"),
        (r"C:\Program Files\App\APP.EXE", "APP"),
        ("", None),
    ],
)
def test_application_name_from_path(path: str, expected: str | None) -> None:
    assert application_name_from_path(path) == expected


def test_json_output_has_stable_status_value() -> None:
    observation = ForegroundObservation(
        sequence=1,
        observed_at="2026-09-17T10:00:00.000-04:00",
        monotonic_ms=123,
        hwnd=100,
        pid=42,
        application_name="Example",
        executable_path=r"C:\Example.exe",
        status=ResolutionStatus.IDENTIFIED,
    )

    payload = json.loads(format_observation(observation, as_json=True))

    assert payload["status"] == "identified"
    assert payload["application_name"] == "Example"

