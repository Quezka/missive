"""Work off the UI thread, and restarting the app."""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QProcess, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QApplication


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)  # the exception


class _Worker(QRunnable):
    """Runs a network-only call off the UI thread."""

    def __init__(self, call):
        super().__init__()
        self.call = call
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.call())
        except Exception as e:  # reported on the UI thread; never crash the app
            self.signals.failed.emit(e)


def run_in_background(call, on_done, on_failed) -> _Worker:
    worker = _Worker(call)
    worker.signals.done.connect(on_done)
    worker.signals.failed.connect(on_failed)
    QThreadPool.globalInstance().start(worker)
    return worker


def restart_app():
    """Start a fresh Missive and quit this one (the window asks about unsaved changes)."""
    for window in QApplication.topLevelWidgets():
        if window.isWindow() and window.isVisible() and not window.close():
            return
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    QProcess.startDetached(sys.executable, args)
    QApplication.quit()
