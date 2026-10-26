"""The account setup screen: an address, a password, and (only if the guess is wrong) the server."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ..application.errors import ApplicationError
from ..application.records import AccountDraft
from ..application.services import MailService
from .i18n import _
from .views.common import button, label, primary_button


class _Check(QObject):
    """Tries the sign-in off the UI thread (the network can take a while)."""

    done = Signal(str)  # "" when it worked, else what went wrong

    def __init__(self, service: MailService, draft: AccountDraft):
        super().__init__()
        self._service, self._draft = service, draft

    def run(self):
        try:
            self._service.check_account(self._draft)
            self.done.emit("")
        except ApplicationError as e:
            self.done.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.done.emit(f"{type(e).__name__}: {e}")


class AccountDialog(QDialog):
    def __init__(self, service: MailService, parent=None):
        super().__init__(parent)
        self.service = service
        self.added = None  # the AccountRecord, once saved
        self._host_edited = False
        self._thread: QThread | None = None
        self.setWindowTitle(_("Add a mail account"))
        self.setMinimumWidth(420)

        self.address = QLineEdit(placeholderText="name@example.com")
        self.password = QLineEdit(echoMode=QLineEdit.Password)
        self.name = QLineEdit(placeholderText=_("Home, School, Work…"))
        self.host = QLineEdit(placeholderText="imap.example.com")
        self.port = QSpinBox(minimum=1, maximum=65535, value=993)
        self.username = QLineEdit(placeholderText=_("Same as the address"))
        self.hint = label("", "muted")
        self.hint.setWordWrap(True)
        self.error = QLabel(objectName="danger")
        self.error.setWordWrap(True)
        self.error.hide()
        self.safety = label(_("Missive only reads your mail: it never sends, moves, deletes or marks anything. "
                              "The password is kept in your system's keyring."), "hint")
        self.safety.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow(_("Email address"), self.address)
        form.addRow(_("Password"), self.password)
        form.addRow(_("Name"), self.name)
        self.server_toggle = button(_("Server settings"))
        self.server_toggle.setCheckable(True)
        self.server_box = QWidget()  # only shown when the guessed server needs correcting
        server_form = QFormLayout(self.server_box)
        server_form.setContentsMargins(0, 0, 0, 0)
        server_form.setLabelAlignment(Qt.AlignRight)
        server_form.addRow(_("Server"), self.host)
        server_form.addRow(_("Port"), self.port)
        server_form.addRow(_("Username"), self.username)
        self.server_box.hide()
        self.server_toggle.toggled.connect(self._show_server)
        self.add_button = primary_button(_("Add account"), None)
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._add)
        cancel = button(_("Cancel"))
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.server_toggle)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.add_button)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(form)
        layout.addWidget(self.server_box)
        layout.addWidget(self.hint)
        layout.addWidget(self.error)
        layout.addWidget(self.safety)
        layout.addLayout(buttons)

        self.address.textChanged.connect(self._address_changed)
        self.host.textEdited.connect(lambda _t: setattr(self, "_host_edited", True))
        for edit in (self.address, self.password):
            edit.textChanged.connect(self._update_button)

    # ---- the form ----

    def _show_server(self, shown: bool):
        self.server_box.setVisible(shown)
        self.adjustSize()

    def _address_changed(self, text: str):
        guess = self.service.guess_server(text)
        if guess is None:
            self.hint.setText("")
            return
        if not self._host_edited:
            self.host.setText(guess.host)
            self.port.setValue(guess.port)
        if guess.unsupported:
            self.hint.setText(_("This provider only allows OAuth sign-in, which Missive doesn't support yet."))
        elif guess.app_password:
            self.hint.setText(_("This provider asks for an app password, made in your account's security "
                                "settings, instead of your normal password."))
        else:
            self.hint.setText("")

    def _update_button(self, *_a):
        guess = self.service.guess_server(self.address.text())
        ok = guess is not None and not guess.unsupported and bool(self.password.text())
        self.add_button.setEnabled(ok and self._thread is None)

    def draft(self) -> AccountDraft:
        guess = self.service.guess_server(self.address.text())
        host = self.host.text().strip() or (guess.host if guess else "")
        port = self.port.value()
        username = self.username.text().strip()
        return AccountDraft(self.name.text(), self.address.text(), host, port,
                            username or self.address.text().strip(), self.password.text())

    # ---- checking and saving ----

    def _add(self):
        self.error.hide()
        self.add_button.setEnabled(False)
        self.add_button.setText(_("Checking…"))
        self._thread = QThread(self)
        self._worker = _Check(self.service, self.draft())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._checked)  # a method of this dialog: delivered on the UI thread
        self._thread.start()

    @Slot(str)
    def _checked(self, problem: str):
        self._thread.quit()
        self._thread.wait()
        self._thread = None
        self.add_button.setText(_("Add account"))
        if problem:
            self.error.setText(_(problem))
            self.error.show()
            self._update_button()
            return
        try:  # on the UI thread: it writes to the database
            self.added = self.service.add_new_account(self.draft())
        except ApplicationError as e:
            self.error.setText(str(e))
            self.error.show()
            self._update_button()
            return
        self.accept()

