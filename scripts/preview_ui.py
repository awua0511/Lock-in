"""Render deterministic Qt previews without touching real settings or windows."""
# ruff: noqa: E402 -- configure the offscreen Qt platform before importing Qt.

import argparse
import os
from datetime import date, time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path("build/ui-preview"))
parser.add_argument("--scale", default="1")
args = parser.parse_args()
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = args.scale

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from lock_in.domain.models import (
    ApplicationAllowlistEntry,
    ApplicationIdentity,
    ApplicationKind,
    Recurrence,
    RecurrenceKind,
    Schedule,
    TargetType,
    WebsiteAllowlistEntry,
)
from lock_in.reviews.models import DailyReview, ReviewDetail
from lock_in.rules.application_policy import AttentionPrompt, FocusConfiguration
from lock_in.ui.main_window import MainWindow
from lock_in.ui.prompt_dialog import AttentionPromptDialog
from lock_in.ui.theme import apply_theme

application = QApplication([])
for font_name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font_name
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
apply_theme(application)
window = MainWindow(
    hide_on_close=False,
    on_save_schedule=lambda _: None,
    on_delete_schedule=lambda _: None,
    on_save_application=lambda _: None,
    on_delete_application=lambda _: None,
    on_set_capture=lambda _: None,
    on_save_settings=lambda _: None,
    on_save_website=lambda _: None,
    on_delete_website=lambda _: None,
)
window.update_configuration(
    FocusConfiguration(
        schedules=(
            Schedule(
                "Writing & research",
                time(9),
                time(11),
                "local",
                (Recurrence(RecurrenceKind.WEEKLY, weekday=date.today().weekday()),),
            ),
        ),
        applications=(
            ApplicationAllowlistEntry(
                ApplicationIdentity(
                    ApplicationKind.WIN32,
                    "Visual Studio Code",
                    executable_path=r"C:\Apps\Code.exe",
                )
            ),
        ),
        websites=(
            WebsiteAllowlistEntry("github.com"),
            WebsiteAllowlistEntry("docs.python.org"),
        ),
    )
)
window.report_browser_health("Chrome: 1 connected profile · Edge: 1 connected profile")
args.output.mkdir(parents=True, exist_ok=True)
window.show()
for name in window._page_names:
    window._go(name)
    if name == "Reviews":
        window.update_review(
            DailyReview(
                date.today(),
                4800000,
                240000,
                3,
                1,
                3,
                1,
                1,
                (ReviewDetail("13:20", "website", "example.com", "continue", "entry"),),
            )
        )
    application.processEvents()
    window.grab().save(str(args.output / f"{name.lower()}.png"))
window.resize(760, 540)
window._go("Applications")
application.processEvents()
window.grab().save(str(args.output / "narrow.png"))
prompt = AttentionPromptDialog(
    AttentionPrompt(
        "demo",
        1,
        1,
        "Chrome",
        "chrome.exe",
        None,
        ("demo",),
        ("Writing & research",),
        target_type=TargetType.WEBSITE,
        target_key="example.com",
    ),
    lambda *args: None,
)
prompt.show()
application.processEvents()
prompt.grab().save(str(args.output / "prompt.png"))
prompt.dismiss_stale()
window.close()
print(f"Rendered UI previews at scale {args.scale}: {args.output.resolve()}")
