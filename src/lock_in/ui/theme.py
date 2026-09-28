"""Shared, DPI-independent visual language for the desktop UI."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout

STYLESHEET = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #223b43; }
QMainWindow, QDialog { background: #f4f6f4; }
QWidget#sidebar { background: #183a3c; }
QLabel#brand { color: #ffffff; font-size: 24pt; font-weight: 700; }
QLabel#sidebarNote { color: #b6cbc8; font-size: 9pt; }
QListWidget#navigation { background: transparent; border: none; color: #d3e2de; }
QListWidget#navigation::item { padding: 14px 16px; border: none; margin: 3px 0; border-radius: 8px; }
QListWidget#navigation::item:selected { background: #315453; color: white; }
QListWidget#navigation::item:hover:!selected { background: #244749; }
QLabel#eyebrow { color: #53756e; font-size: 9pt; font-weight: 600; }
QLabel#pageTitle { font-size: 25pt; font-weight: 700; color: #183a3c; }
QLabel#subtitle, QLabel#muted { color: #596e72; }
QLabel#heroTitle { font-size: 23pt; font-weight: 600; color: #183a3c; }
QLabel#metricValue { font-size: 25pt; font-weight: 600; color: #183a3c; }
QFrame#card { background: #ffffff; border: 1px solid #dce5e0; border-radius: 12px; }
QFrame#hero { background: #e2efe8; border: 1px solid #d0e2d7; border-radius: 14px; }
QGroupBox { background: #ffffff; border: 1px solid #dce5e0; border-radius: 10px;
    margin-top: 14px; padding: 22px 18px 18px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 18px; padding: 0 6px; }
QPushButton { background: #ffffff; border: 1px solid #c6d6cf; border-radius: 7px;
    padding: 9px 15px; font-weight: 600; min-height: 19px; }
QPushButton:hover { background: #edf4ef; border-color: #689589; }
QPushButton:pressed { background: #dce9e2; }
QPushButton:focus { border: 2px solid #2a8873; padding: 8px 14px; }
QPushButton:disabled { color: #738482; background: #eef1ef; border-color: #dde4df; }
QPushButton[variant="primary"] { background: #246958; color: white; border-color: #246958; }
QPushButton[variant="primary"]:hover { background: #185342; }
QPushButton[variant="primary"]:disabled { background: #9eb9b0; border-color: #9eb9b0; }
QPushButton[variant="danger"] { color: #994e43; }
QLineEdit, QComboBox, QSpinBox, QTimeEdit, QDateEdit { background: white; border: 1px solid #c6d6cf;
    border-radius: 6px; padding: 7px; min-height: 20px; selection-background-color: #d3e9dd; selection-color: #183a3c; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus, QDateEdit:focus { border-color: #246958; }
QComboBox QAbstractItemView { background: white; color: #223b43; selection-background-color: #d3e9dd; selection-color: #183a3c; }
QListWidget { background: white; border: 1px solid #dce5e0; border-radius: 9px; padding: 6px; outline: none; }
QListWidget::item { padding: 11px 9px; border-bottom: 1px solid #edf1ee; }
QListWidget::item:selected { background: #e0eee6; color: #183a3c; border-radius: 5px; }
QCheckBox { spacing: 6px; padding: 4px 0; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { width: 10px; background: transparent; }
QScrollBar::handle:vertical { background: #bfcec7; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #e8eeea; border-top: 1px solid #d4dfd8; }
QStatusBar::item { border: none; }
QLabel#failureBanner { background: #fff0d5; color: #77531c; border: 1px solid #e5c88d; border-radius: 7px; padding: 10px; }
QToolTip { background: #183a3c; color: white; border: none; padding: 6px; }
"""


def application_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#246958"))
    painter.drawRoundedRect(0, 0, 64, 64, 15, 15)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 33, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "L")
    painter.end()
    return QIcon(pixmap)


def apply_theme(application: QApplication) -> None:
    application.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#f4f6f4"),
        (QPalette.ColorRole.WindowText, "#223b43"),
        (QPalette.ColorRole.Base, "#ffffff"),
        (QPalette.ColorRole.Text, "#223b43"),
        (QPalette.ColorRole.Button, "#ffffff"),
        (QPalette.ColorRole.ButtonText, "#223b43"),
        (QPalette.ColorRole.Highlight, "#d3e9dd"),
        (QPalette.ColorRole.HighlightedText, "#183a3c"),
    ):
        palette.setColor(role, QColor(color))
    application.setPalette(palette)
    application.setFont(QFont("Segoe UI", 10))
    application.setStyleSheet(STYLESHEET)
    application.setWindowIcon(application_icon())


def text_label(text: str, style: str = "muted") -> QLabel:
    label = QLabel(text)
    label.setObjectName(style)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def metric_card(title: str, value: str) -> tuple[QFrame, QLabel]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    label = text_label(value, "metricValue")
    layout.addWidget(label)
    layout.addWidget(text_label(title))
    return frame, label
