"""The Settings tab: accounts, how often to check, appearance, language, size and updates."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import APP_NAME, HOMEPAGE, __version__
from ..application.services import MailService
from . import i18n, theme, uiscale
from .background import restart_app
from .i18n import _
from .views.common import (Card, Page, Segmented, button, caption, icon_button, label, primary_button,
                           scrolling)

CHECK_CHOICES = (2, 5, 10, 15, 30, 0)  # minutes; 0 = only when asked
DEFAULT_CHECK = 5


def check_minutes() -> int:
    """How often Missive looks for new mail by itself (0: never, only with the refresh button)."""
    try:
        value = int(QSettings().value("mail/check_minutes", DEFAULT_CHECK))
    except (TypeError, ValueError):
        return DEFAULT_CHECK
    return value if value in CHECK_CHOICES else DEFAULT_CHECK


class SettingsPage(Page):
    back = Signal()
    addAccount = Signal()
    removeAccount = Signal(int)
    checkEveryChanged = Signal(int)  # minutes

    def __init__(self, service: MailService, updates=None, updater=None, parent=None):
        super().__init__(parent)
        self.service = service
        self.title.setText(_("Settings"))
        self.subtitle.setText(_("{app} {version}").format(app=APP_NAME, version=__version__))
        back = icon_button("chevron-left", _("Back to the mail (Esc)"))
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.back.emit)
        self.leading.addWidget(back)

        # ---- accounts
        accounts = Card(_("Accounts"))
        self.account_rows = QVBoxLayout()
        self.account_rows.setSpacing(6)
        accounts.body.addLayout(self.account_rows)
        add = button(_("Add account"), "plus")
        add.clicked.connect(self.addAccount.emit)
        accounts.add(add)
        accounts.add(label(_("Removing an account only forgets it here: nothing changes on the mail server."), "hint"))

        # ---- mail
        mail = Card(_("Mail"))
        mail.add(caption(_("Check for new mail")))
        self.check_every = QComboBox()
        for minutes in CHECK_CHOICES:
            self.check_every.addItem(_("Every {n} minutes").format(n=minutes) if minutes else
                                     _("Only when I press refresh"), minutes)
        self.check_every.setCurrentIndex(max(0, self.check_every.findData(check_minutes())))
        self.check_every.currentIndexChanged.connect(self._check_changed)
        mail.add(self.check_every)

        # ---- appearance
        manager = theme.manager()
        appearance = Card(_("Appearance"))
        mode = Segmented([("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))])
        mode.set_value(manager.mode)
        mode.changed.connect(manager.set_mode)
        appearance.add(mode)
        contrast = QCheckBox(_("High contrast (black and white, thick lines)"))
        contrast.setChecked(manager.contrast)
        contrast.toggled.connect(manager.set_contrast)
        appearance.add(contrast)

        # ---- language and size (both apply after a restart)
        language = Card(_("Language"))
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES:
            self.language.addItem(_(name) if code == "" else name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(i18n.chosen_language())))
        self.language.currentIndexChanged.connect(self._language_changed)
        language.add(caption(_("Interface language")))
        language.add(self.language)
        size = Card(_("Interface size"))
        self.scale = QComboBox()
        for choice in uiscale.CHOICES:
            self.scale.addItem(_("Automatic") if choice == "auto" else f"{choice}%", choice)
        self.scale.setCurrentIndex(max(0, self.scale.findData(uiscale.chosen())))
        self.scale.currentIndexChanged.connect(self._scale_changed)
        size.add(self.scale)
        size.add(label(_("Language and size apply after a restart."), "hint"))
        self.restart = primary_button(_("Restart Missive now"), "refresh")
        self.restart.hide()
        self.restart.clicked.connect(restart_app)
        size.add(self.restart)

        # ---- updates
        update_card = Card(_("Updates"))
        auto = QCheckBox(_("Check for new versions once a day"))
        check = button(_("Check now"), "refresh")
        if updates is not None:
            auto.setChecked(updates.auto_check())
            auto.toggled.connect(updates.set_auto_check)
        else:
            auto.setEnabled(False)
        check.setEnabled(updater is not None)
        if updater is not None:
            check.clicked.connect(lambda: updater.check_now())
        site = button(_("Open the project page"), "arrow-up-right")
        site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HOMEPAGE)))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(check)
        row.addWidget(site)
        row.addStretch()
        update_card.add(auto)
        update_card.body.addLayout(row)
        update_card.add(label(_("You have version {version}.").format(version=__version__), "hint"))

        column = QVBoxLayout()
        column.setSpacing(12)
        for card in (accounts, mail, appearance, language, size, update_card):
            column.addWidget(card)
        column.addStretch()
        holder = QWidget()
        holder.setMaximumWidth(640)
        holder.setLayout(column)
        centre = QHBoxLayout()
        centre.addWidget(holder, 1)
        centre.addStretch(0)
        self.root.addWidget(scrolling(centre), 1)
        self.refresh_accounts()

    def refresh_accounts(self):
        while self.account_rows.count():
            item = self.account_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)  # gone at once, not at the next turn of the event loop
                widget.deleteLater()
        accounts = self.service.accounts()
        if not accounts:
            self.account_rows.addWidget(label(_("No account yet."), "hint"))
        for account in accounts:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            names = QVBoxLayout()
            names.setSpacing(0)
            names.addWidget(QLabel(account.name, objectName="sheetTitle"))
            names.addWidget(label(account.address, "muted"))
            line.addLayout(names, 1)
            remove = button(_("Remove…"), "trash")
            remove.clicked.connect(lambda _c=False, a=account.id: self.removeAccount.emit(a))
            line.addWidget(remove, 0, Qt.AlignVCenter)
            self.account_rows.addWidget(row)

    def _check_changed(self):
        minutes = self.check_every.currentData()
        QSettings().setValue("mail/check_minutes", minutes)
        self.checkEveryChanged.emit(minutes)

    def _scale_changed(self):
        uiscale.set_chosen(self.scale.currentData())
        self.restart.show()

    def _language_changed(self):
        i18n.set_chosen_language(self.language.currentData())
        self.restart.show()
