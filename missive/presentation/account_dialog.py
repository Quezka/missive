"""The account setup screen: an address and how to sign in (a password, or Google / Microsoft in the
browser), and (only if the guess is wrong) the server."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from ..application.errors import ApplicationError
from ..application.records import AccountDraft
from ..application.services import MailService
from .i18n import _
from .views.common import button, label, primary_button


class _Check(QObject):
    """Signs in off the UI thread (the network, and the user's browser, can take a while)."""

    done = Signal(str, str)  # (what went wrong or "", the secret to keep: the password or OAuth refresh token)

    def __init__(self, service: MailService, draft: AccountDraft):
        super().__init__()
        self._service, self._draft = service, draft

    def run(self):
        try:
            draft = self._draft
            if draft.auth != "password":  # Google / Microsoft: approve in the browser first
                draft = replace(draft, password=self._service.authorize(draft.auth, draft.address))
            self._service.check_account(draft)
            self.done.emit("", draft.password)
        except ApplicationError as e:
            self.done.emit(str(e), "")
        except Exception as e:  # noqa: BLE001
            self.done.emit(f"{type(e).__name__}: {e}", "")


class AccountDialog(QDialog):
    def __init__(self, service: MailService, parent=None):
        super().__init__(parent)
        self.service = service
        self.added = None  # the AccountRecord, once saved
        self._host_edited = False
        self._method_edited = False
        self._smtp_edited = False
        self._thread: QThread | None = None
        self.setWindowTitle(_("Add a mail account"))
        self.setMinimumWidth(420)

        self.address = QLineEdit(placeholderText="name@example.com")
        self.method = QComboBox()
        self.method.addItem(_("Password"), "password")
        self.method.addItem(_("Google"), "google")
        self.method.addItem(_("Microsoft (Outlook, Hotmail, Microsoft 365)"), "microsoft")
        self.password = QLineEdit(echoMode=QLineEdit.Password)
        self.name = QLineEdit(placeholderText=_("Home, School, Work…"))
        self.host = QLineEdit(placeholderText="imap.example.com")
        self.port = QSpinBox(minimum=1, maximum=65535, value=993)
        self.username = QLineEdit(placeholderText=_("Same as the address"))
        self.smtp_host = QLineEdit(placeholderText="smtp.example.com")
        self.smtp_port = QSpinBox(minimum=1, maximum=65535, value=587)
        self.hint = label("", "muted")
        self.hint.setWordWrap(True)
        self.error = QLabel(objectName="danger")
        self.error.setWordWrap(True)
        self.error.hide()
        self.safety = label(_("Missive reads your mail without changing it and sends only what you write yourself. "
                              "The password, or the sign-in token for Google and Microsoft, is kept in your "
                              "system's keyring."), "hint")
        self.safety.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.form = form
        form.addRow(_("Email address"), self.address)
        form.addRow(_("Sign in with"), self.method)
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
        server_form.addRow(_("Outgoing server"), self.smtp_host)
        server_form.addRow(_("Outgoing port"), self.smtp_port)
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
        self.method.activated.connect(self._method_chosen)
        self.host.textEdited.connect(lambda _t: setattr(self, "_host_edited", True))
        self.smtp_host.textEdited.connect(lambda _t: setattr(self, "_smtp_edited", True))
        for edit in (self.address, self.password):
            edit.textChanged.connect(self._update_button)
        self._method_changed()

    # ---- the form ----

    def _show_server(self, shown: bool):
        self.server_box.setVisible(shown)
        self.adjustSize()

    def auth(self) -> str:
        return self.method.currentData()

    def _address_changed(self, text: str):
        guess = self.service.guess_server(text)
        if guess is not None and not self._method_edited:
            wanted = guess.oauth if guess.oauth and (guess.oauth != "google"
                                                      or self.service.oauth_available("google")) else "password"
            self.method.setCurrentIndex(self.method.findData(wanted))
        self._method_changed()

    def _method_chosen(self, _index: int):
        self._method_edited = True  # the user knows better than the address (a school on Google, say)
        self._method_changed()

    def _method_changed(self):
        """Show what the chosen way to sign in needs, and the server it talks to."""
        auth = self.auth()
        oauth = auth != "password"
        self.form.setRowVisible(self.password, not oauth)
        guess = self.service.guess_server(self.address.text())
        if not self._host_edited:
            host = self.service.oauth_host(auth) if oauth else (guess.host if guess else "")
            self.host.setText(host)
            self.port.setValue(993 if oauth or guess is None else guess.port)
        if not self._smtp_edited and guess is not None:
            smtp_host, smtp_port = self.service.smtp_server(self.address.text(), auth)
            self.smtp_host.setText(smtp_host)
            self.smtp_port.setValue(smtp_port)
        if oauth and not self.service.oauth_available(auth):
            self.hint.setText(_("This sign-in isn't set up yet: add its client ID (see docs/OAUTH.md)."))
        elif oauth:
            self.hint.setText(_("Your browser opens so you can approve Missive. No password is typed or kept here."))
        elif guess is not None and guess.oauth == "microsoft":
            self.hint.setText(_("Outlook and Hotmail no longer accept passwords for mail programs: sign in with "
                                "Microsoft instead."))
        elif guess is not None and guess.app_password:
            self.hint.setText(_("This provider asks for an app password, made in your account's security "
                                "settings, instead of your normal password."))
        else:
            self.hint.setText("")
        self.add_button.setText({"google": _("Sign in with Google"), "microsoft": _("Sign in with Microsoft")}
                                .get(auth, _("Add account")))
        self._update_button()

    def _update_button(self, *_a):
        guess = self.service.guess_server(self.address.text())
        auth = self.auth()
        if auth == "password":
            ok = guess is not None and bool(self.password.text())
        else:
            ok = guess is not None and self.service.oauth_available(auth)
        self.add_button.setEnabled(ok and self._thread is None)

    def draft(self) -> AccountDraft:
        guess = self.service.guess_server(self.address.text())
        host = self.host.text().strip() or (guess.host if guess else "")
        port = self.port.value()
        username = self.username.text().strip()
        return AccountDraft(self.name.text(), self.address.text(), host, port,
                            username or self.address.text().strip(), self.password.text(), self.auth(),
                            self.smtp_host.text().strip(), self.smtp_port.value())

    # ---- checking and saving ----

    def _add(self):
        self.error.hide()
        self.add_button.setEnabled(False)
        waiting = self.auth() != "password"
        self.add_button.setText(_("Waiting for your browser…") if waiting else _("Checking…"))
        if waiting:
            self.hint.setText(_("Approve Missive in the browser window that just opened."))
        self._thread = QThread(self)
        self._worker = _Check(self.service, self.draft())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._checked)  # a method of this dialog: delivered on the UI thread
        self._thread.start()

    def _stop_worker(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None

    def reject(self):
        """Closing while the browser is open stops the wait first (it can't be left running)."""
        if self._thread is not None:
            self._worker.done.disconnect(self._checked)
            self.service.cancel_authorization()
            self._stop_worker()
        super().reject()

    @Slot(str, str)
    def _checked(self, problem: str, secret: str):
        self._stop_worker()
        self._method_changed()  # button text and hint back to normal
        if problem:
            self.error.setText(_(problem))
            self.error.show()
            return
        try:  # on the UI thread: it writes to the database
            self.added = self.service.add_new_account(replace(self.draft(), password=secret))
        except ApplicationError as e:
            self.error.setText(_(str(e)))
            self.error.show()
            self._update_button()
            return
        self.accept()
