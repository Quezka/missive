"""Updating Missive from inside the app: the background check and the update dialog."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTextBrowser, QVBoxLayout,
)

from ..application.errors import ApplicationError
from ..application.updates import AvailableUpdate, UpdateService
from .background import restart_app, run_in_background
from .i18n import _


def _message(error: Exception) -> str:
    return _(str(error)) if isinstance(error, ApplicationError) else _(
        "Something went wrong: {error}").format(error=error)


class UpdateChecker(QObject):
    """Checks GitHub about once a day (starting shortly after launch), and on request."""

    available = Signal(object)  # AvailableUpdate
    DELAY_MS = 10_000
    HOURLY_MS = 60 * 60_000

    def __init__(self, updates: UpdateService, parent=None):
        super().__init__(parent)
        self.updates = updates
        self._worker = None
        self._interactive = False
        self.timer = QTimer(self, interval=self.HOURLY_MS)
        self.timer.timeout.connect(self._maybe_check)
        self.timer.start()
        QTimer.singleShot(self.DELAY_MS, self._maybe_check)

    @property
    def checking(self) -> bool:
        return self._worker is not None

    def _maybe_check(self):
        if self.updates.due():
            self.check_now(interactive=False)

    def check_now(self, interactive: bool = True):
        """`interactive`: the user asked, so also say when there's nothing new or it failed."""
        if self._worker is not None:
            return
        self._interactive = interactive
        self._worker = run_in_background(self.updates.check, self._checked,
                                         self._failed)

    def _checked(self, update: AvailableUpdate | None):
        self._worker = None
        self.updates.mark_checked()
        parent = self.parent()
        if update is None:
            if self._interactive:
                QMessageBox.information(parent, _("No updates"), _(
                    "You have the latest version of Missive ({version}).").format(
                        version=self.updates.current_version))
            return
        if not self._interactive and self.updates.skipped(update.version):
            return
        self.available.emit(update)
        UpdateDialog(self.updates, update, parent).exec()

    def _failed(self, error: Exception):
        self._worker = None
        if self._interactive:
            QMessageBox.warning(self.parent(), _("Couldn't check for updates"), _message(error))


class UpdateDialog(QDialog):
    def __init__(self, updates: UpdateService, update: AvailableUpdate, parent=None):
        super().__init__(parent)
        self.updates = updates
        self.update_info = update
        self._worker = None
        self.setWindowTitle(_("Update available"))
        self.setMinimumSize(520, 420)

        title = QLabel(_("Missive {version} is available").format(version=update.version),
                       objectName="sheetTitle")
        current = QLabel(_("You have {version}. Here's what's new:").format(
            version=update.current), objectName="hint")
        notes = QTextBrowser(objectName="sheetBody", openExternalLinks=True)
        notes.setMarkdown(update.notes or _("No release notes."))
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status = QLabel("", objectName="hint")
        self.status.setWordWrap(True)
        self.status.hide()

        self.skip_btn = QPushButton(_("Skip this version"))
        self.skip_btn.clicked.connect(self._skip)
        self.later_btn = QPushButton(_("Later"))
        self.later_btn.clicked.connect(self.reject)
        if update.can_install:
            self.go_btn = QPushButton(_("Update now"), objectName="primary")
            self.go_btn.clicked.connect(self._download)
        else:
            self.go_btn = QPushButton(_("Open download page"), objectName="primary")
            self.go_btn.clicked.connect(self._open_page)
            self._show_status(_("This copy of Missive can't update itself (for example when it "
                                "runs from source). Download the new version from GitHub."))
        self.go_btn.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.skip_btn)
        buttons.addStretch()
        buttons.addWidget(self.later_btn)
        buttons.addWidget(self.go_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(current)
        layout.addWidget(notes, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

    def _show_status(self, text: str, error: bool = False):
        self.status.setText(text)
        self.status.setObjectName("danger" if error else "hint")
        self.status.style().polish(self.status)
        self.status.setVisible(bool(text))

    def _busy(self, busy: bool):
        for button in (self.skip_btn, self.later_btn, self.go_btn):
            button.setEnabled(not busy)

    def _skip(self):
        self.updates.skip(self.update_info.version)
        self.reject()

    def _open_page(self):
        QDesktopServices.openUrl(QUrl(self.update_info.page_url))
        self.accept()

    # ---- download and install ------------------------------------------------------

    def _download(self):
        self._busy(True)
        self.progress.setRange(0, 0)
        self.progress.show()
        self._show_status(_("Downloading…"))
        progress = _Progress()
        progress.changed.connect(self._progressed)
        self._worker = run_in_background(
            lambda: self.updates.download(self.update_info, progress.changed.emit),
            self._downloaded, self._failed)
        self._progress = progress

    def _progressed(self, done: int, total: int):
        if total:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
            self._show_status(_("Downloading… {done} of {total} MB").format(
                done=f"{done / 1e6:.1f}", total=f"{total / 1e6:.1f}"))

    def _downloaded(self, path: str):
        self.progress.setRange(0, 0)
        self._show_status(_("Installing… your system may ask for your password."))
        self._worker = run_in_background(lambda: self.updates.install(path),
                                         self._installed, self._failed)

    def _installed(self, installer_took_over: bool):
        self._worker = None
        self.accept()
        if installer_took_over:  # Windows: the setup replaces the files and restarts Missive
            QApplication.quit()
        else:  # Linux: the new version is installed; start it
            restart_app()

    def _failed(self, error: Exception):
        self._worker = None
        self.progress.hide()
        self._busy(False)
        self._show_status(_message(error), error=True)


class _Progress(QObject):
    """Carries download progress from the worker thread to the dialog."""

    changed = Signal(int, int)
