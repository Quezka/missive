"""Keeping windows and dialogs inside the screen (a laptop at 1366x768 is small)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QScrollArea, QVBoxLayout, QWidget

MARGIN = 24  # room left for the title bar and panels


def available(widget: QWidget | None = None):
    screen = (widget.screen() if widget is not None else None) or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen else None


def clamp_window(window: QWidget, width: int, height: int, min_width: int, min_height: int):
    """Size a window as asked, but never bigger than the screen."""
    area = available(window)
    if area is None:
        window.resize(width, height)
        window.setMinimumSize(min_width, min_height)
        return
    max_w, max_h = area.width() - MARGIN, area.height() - MARGIN
    window.setMinimumSize(min(min_width, max_w), min(min_height, max_h))
    window.resize(min(width, max_w), min(height, max_h))


def clamp_dialog(dialog: QWidget, width: int, height: int):
    area = available(dialog)
    if area is None:
        dialog.resize(width, height)
        return
    dialog.resize(min(width, area.width() - MARGIN * 2), min(height, int(area.height() * 0.9)))


def scrollable(dialog: QDialog):
    """Put what the dialog shows in a scroll area, sized to fit the screen: a tall dialog
    scrolls instead of running off the bottom. Call it once the dialog is fully built."""
    layout = dialog.layout()
    content = QWidget()
    holder = QWidget()
    holder.setLayout(layout)  # a layout belongs to one widget: detach it first
    content.setLayout(layout)
    del holder
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addWidget(scroll)
    hint = content.sizeHint()
    area = available(dialog)
    width = max(hint.width() + 18, dialog.minimumWidth())  # room for the scroll bar
    height = hint.height() + 4
    if area is not None:
        width = min(width, area.width() - MARGIN * 2)
        height = min(height, int(area.height() * 0.9))
        dialog.setMinimumWidth(min(dialog.minimumWidth(), width))
    dialog.resize(width, height)
