"""Writing a message: who it is from and to, a subject and the text. Send hands it back to the window,
which waits a few seconds (so it can be undone) and then sends it."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QVBoxLayout,
)

from ..application.errors import ApplicationError
from ..application.records import DraftRecord
from ..application.services import MailService
from . import fit
from .i18n import _
from .views.common import button, label, primary_button


class ComposeDialog(QDialog):
    """Not modal: you can keep reading mail while you write."""

    send_requested = Signal(object)  # DraftRecord

    def __init__(self, service: MailService, draft: DraftRecord, parent=None):
        super().__init__(parent)
        self.service = service
        self._initial = draft
        self.setWindowTitle(draft.subject or _("New message"))
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        fit.clamp_dialog(self, 720, 600)

        self.sender = QComboBox()
        for account in service.accounts():
            self.sender.addItem(f"{account.name}  <{account.address}>", account.id)
        self.sender.setCurrentIndex(max(0, self.sender.findData(draft.account_id)))
        self.to = QLineEdit(draft.to, placeholderText=_("Names or addresses, separated by commas"))
        self.cc = QLineEdit(draft.cc)
        self.bcc = QLineEdit(draft.bcc)
        self.subject = QLineEdit(draft.subject)
        self.body = QPlainTextEdit(draft.text)
        self.error = QLabel(objectName="danger")
        self.error.setWordWrap(True)
        self.error.hide()

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.addRow(_("From"), self.sender)
        self.form.addRow(_("To"), self.to)
        self.form.addRow(_("Cc"), self.cc)
        self.form.addRow(_("Bcc"), self.bcc)
        self.form.addRow(_("Subject"), self.subject)
        self.more = button(_("Cc and Bcc"))
        self.more.setCheckable(True)
        self.more.toggled.connect(self._show_copies)
        self.send_button = primary_button(_("Send"), "send")
        self.send_button.clicked.connect(self._send)
        self.discard_button = button(_("Discard"))
        self.discard_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.more)
        buttons.addStretch()
        buttons.addWidget(label(_("Ctrl+Enter sends"), "hint"))
        buttons.addWidget(self.discard_button)
        buttons.addWidget(self.send_button)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(self.form)
        layout.addWidget(self.body, 1)
        layout.addWidget(self.error)
        layout.addLayout(buttons)

        self.more.setChecked(bool(draft.cc or draft.bcc))
        self._show_copies(self.more.isChecked())
        for key in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(key), self, activated=self._send)
        (self.body if draft.to else self.to).setFocus()
        if draft.to:
            cursor = self.body.textCursor()
            cursor.setPosition(0)  # a reply starts above the quoted text
            self.body.setTextCursor(cursor)

    def _show_copies(self, shown: bool):
        for field in (self.cc, self.bcc):
            self.form.setRowVisible(field, shown)

    def draft(self) -> DraftRecord:
        return replace(self._initial, account_id=self.sender.currentData(), to=self.to.text().strip(),
                       cc=self.cc.text().strip(), bcc=self.bcc.text().strip(), subject=self.subject.text().strip(),
                       text=self.body.toPlainText())

    def _changed(self) -> bool:
        return self.draft() != self._initial

    def _send(self):
        draft = self.draft()
        try:
            self.service.check_draft(draft)
        except ApplicationError as e:
            self.error.setText(_(str(e)))
            self.error.show()
            return
        if not draft.subject and not draft.text.strip():
            if QMessageBox.question(self, self.windowTitle(), _("Send an empty message?")) != QMessageBox.Yes:
                return
        elif not draft.subject:
            if QMessageBox.question(self, self.windowTitle(), _("Send without a subject?")) != QMessageBox.Yes:
                return
        self._sending = True
        self.send_requested.emit(draft)
        self.close()

    def reject(self):
        if getattr(self, "_sending", False) or not self._changed():
            return super().reject()
        answer = QMessageBox.question(self, self.windowTitle(), _("Discard this message?"))
        if answer == QMessageBox.Yes:
            self._sending = True  # decided: closing must not ask again
            super().reject()

    def closeEvent(self, event):
        if getattr(self, "_sending", False) or not self._changed():
            return super().closeEvent(event)
        if QMessageBox.question(self, self.windowTitle(), _("Discard this message?")) == QMessageBox.Yes:
            self._sending = True  # decided: no more questions
            return super().closeEvent(event)
        event.ignore()
