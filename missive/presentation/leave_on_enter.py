"""Pressing Enter in a one-line box finishes with it: the cursor stops blinking and the box
lets go of the focus (what the key does first, like adding a task or searching, still
happens)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLineEdit

ENTER = (Qt.Key_Return, Qt.Key_Enter)


class _LeaveOnEnter(QObject):
    def eventFilter(self, obj, event):
        if (event.type() == QEvent.KeyPress and event.key() in ENTER
                and isinstance(obj, QLineEdit) and not event.isAutoRepeat()):
            # After the box has handled the key (a default button, returnPressed…).
            QTimer.singleShot(0, obj, lambda: _let_go(obj))
        return False


def _let_go(box: QLineEdit) -> None:
    if box.hasFocus():
        box.deselect()
        box.clearFocus()


def install(app) -> None:
    watcher = _LeaveOnEnter(app)
    app.installEventFilter(watcher)
    app._leave_on_enter = watcher  # keep it alive
