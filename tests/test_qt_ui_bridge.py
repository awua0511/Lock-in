from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, QTimer, Slot
from PySide6.QtWidgets import QApplication

from lock_in.ui.bridge import QtUiBridge


class Receiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None

    @Slot()
    def receive(self) -> None:
        self.thread = QThread.currentThread()


def test_worker_emission_is_delivered_on_qt_thread() -> None:
    application = QApplication.instance() or QApplication([])
    bridge = QtUiBridge()
    receiver = Receiver()
    bridge.show_main_window_signal.connect(receiver.receive)

    worker = threading.Thread(target=bridge.show_main_window)
    worker.start()
    worker.join(1)
    QTimer.singleShot(50, application.quit)
    application.exec()

    assert receiver.thread is application.thread()
