"""The three panes: folders, conversations, and the message being read."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QModelIndex, QRect, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..application.errors import ApplicationError
from ..application.records import MessageRecord, ThreadRecord
from ..application.services import MailService
from . import theme
from .i18n import _
from .views.common import Card, button, icon_button, label

THREAD, FOLDER = Qt.UserRole + 1, Qt.UserRole + 2
ALL_INBOXES = ("all", None)


def short_when(when: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if when.date() == now.date():
        return f"{when.hour:02d}:{when.minute:02d}"
    if (now.date() - when.date()).days < 7:
        return when.strftime("%a")
    return f"{when.day} {when.strftime('%b')}"


class ThreadDelegate(QStyledItemDelegate):
    """One conversation: who, when, the subject and the start of the latest message."""

    HEIGHT = 74

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.HEIGHT)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        t = theme.current()
        r: ThreadRecord = index.data(THREAD)
        if r is None:
            return super().paint(p, option, index)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        box = option.rect.adjusted(6, 3, -6, -3)
        selected = bool(option.state & QStyle.State_Selected)
        if selected or option.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent_soft if selected else t.hover))
            p.drawRoundedRect(box, 10, 10)
        inner = box.adjusted(14, 8, -10, -6)
        unread = r.unread > 0
        if unread:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t.accent))
            p.drawEllipse(box.left() + 4, box.top() + 14, 8, 8)
        base = QFont(option.font)
        bold = QFont(base)
        bold.setBold(True)
        small = QFont(base)
        small.setPointSizeF(max(7.5, base.pointSizeF() * 0.88))
        when = short_when(r.latest)
        p.setFont(small)
        wide = QFontMetrics(small).horizontalAdvance(when)
        p.setPen(QColor(t.accent if unread else t.muted))
        p.drawText(QRect(inner.right() - wide, inner.top(), wide, 18), Qt.AlignRight | Qt.AlignVCenter, when)
        p.setFont(bold if unread else base)
        p.setPen(QColor(t.text))
        people = r.people + (f"  {r.count}" if r.count > 1 else "")
        p.drawText(QRect(inner.left(), inner.top(), inner.width() - wide - 10, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(bold if unread else base).elidedText(people, Qt.ElideRight, inner.width() - wide - 10))
        p.setFont(bold if unread else base)
        subject = ("⚑ " if r.flagged else "") + r.subject
        p.drawText(QRect(inner.left(), inner.top() + 20, inner.width(), 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(bold if unread else base).elidedText(subject, Qt.ElideRight, inner.width()))
        p.setFont(small)
        p.setPen(QColor(t.muted))
        p.drawText(QRect(inner.left(), inner.top() + 40, inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(small).elidedText(("📎 " if r.has_attachments else "") + r.snippet,
                                                  Qt.ElideRight, inner.width()))
        p.restore()


class MainWindow(QMainWindow):
    def __init__(self, service: MailService):
        super().__init__()
        self.service = service
        self.load_images = False
        self._record: MessageRecord | None = None
        self.setWindowTitle(APP_NAME)
        self.resize(1240, 780)
        self.setMinimumSize(640, 420)

        # ---- folders
        self.folders = QTreeWidget(objectName="folders")
        self.folders.setHeaderHidden(True)
        self.folders.setIndentation(14)
        self.folders.setMinimumWidth(150)
        self.folders.currentItemChanged.connect(lambda *_a: self.show_list())

        # ---- conversations
        self.search = QLineEdit(objectName="search", placeholderText=_("Search mail…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.show_list())
        self.sync_button = icon_button("refresh", _("Check for new mail"))
        self.sync_button.clicked.connect(self.sync)
        self.title = QLabel(objectName="pageTitle")
        self.subtitle = QLabel(objectName="pageSubtitle")
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        head.addWidget(self.sync_button)
        self.threads = QListWidget(objectName="threads")
        self.threads.setItemDelegate(ThreadDelegate(self.threads))
        self.threads.setMouseTracking(True)
        self.threads.setFrameShape(QFrame.NoFrame)
        self.threads.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.threads.currentItemChanged.connect(lambda cur, _prev: self._thread_picked(cur))
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(14, 18, 8, 12)
        middle_layout.setSpacing(10)
        middle_layout.addLayout(head)
        middle_layout.addWidget(self.search)
        middle_layout.addWidget(self.threads, 1)

        # ---- reader
        self.subject = QLabel(objectName="pageTitle", wordWrap=True)
        self.from_line = label("", "muted")
        self.from_line.setWordWrap(True)
        self.notice = label("", "hint")
        self.notice.setWordWrap(True)
        self.load_button = button(_("Load pictures"))
        self.load_button.clicked.connect(self._load_pictures)
        self.star_button = icon_button("star", _("Flag this message"))
        self.star_button.clicked.connect(self._toggle_flag)
        self.reader = QTextBrowser()
        self.reader.setOpenLinks(False)
        self.reader.setFrameShape(QFrame.NoFrame)
        self.reader.anchorClicked.connect(self._link_clicked)
        self.reader.setPlaceholderText(_("Select a message to read it."))
        notice_row = QHBoxLayout()
        notice_row.addWidget(self.notice, 1)
        notice_row.addWidget(self.load_button)
        top = QHBoxLayout()
        top.addWidget(self.subject, 1)
        top.addWidget(self.star_button, 0, Qt.AlignTop)
        card = Card(padding=18)
        card.body.addLayout(top)
        card.add(self.from_line)
        card.body.addLayout(notice_row)
        card.add(self.reader, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 18, 16, 16)
        right_layout.addWidget(card)

        self.split = QSplitter(Qt.Horizontal)
        for w in (self.folders, middle, right):
            self.split.addWidget(w)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 2)
        self.split.setChildrenCollapsible(False)
        sizes = QSettings().value("window/split")
        self.split.setSizes([int(x) for x in sizes] if sizes else [210, 400, 620])
        self.split.splitterMoved.connect(lambda *_a: QSettings().setValue("window/split", self.split.sizes()))
        self.setCentralWidget(self.split)
        theme.themed(self._restyle)
        self.refresh_folders()
        self._clear_reader()

    # ---- the folder tree ----

    def _restyle(self, t):
        self.folders.setStyleSheet(
            f"QTreeWidget#folders {{ background: {t.sidebar}; border: none; padding: 10px 6px; }}"
            f"QTreeWidget#folders::item {{ padding: 6px 8px; border-radius: 8px; }}"
            f"QTreeWidget#folders::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}"
            f"QTreeWidget#folders::item:hover {{ background: {t.hover}; }}")
        self.threads.setStyleSheet(f"QListWidget#threads {{ background: transparent; border: none; }}")
        self.reader.document().setDefaultStyleSheet(
            f"a {{ color: {t.accent}; }} blockquote {{ color: {t.muted}; border-left: 3px solid {t.border}; "
            f"margin-left: 0; padding-left: 10px; }}")

    def refresh_folders(self):
        keep = self._current_scope()
        self.folders.blockSignals(True)
        self.folders.clear()
        accounts = {a.id: a for a in self.service.accounts()}
        folders = self.service.folders()
        unread_all = sum(f.unread for f in folders if f.role == "inbox")
        all_item = QTreeWidgetItem([self._label(_("All inboxes"), unread_all)])
        all_item.setData(0, FOLDER, ALL_INBOXES)
        self.folders.addTopLevelItem(all_item)
        for account in accounts.values():
            top = QTreeWidgetItem([account.name])
            top.setForeground(0, QColor(account.color))
            top.setData(0, FOLDER, (account.id, None))
            top.setExpanded(True)
            self.folders.addTopLevelItem(top)
            for f in (f for f in folders if f.account_id == account.id):
                child = QTreeWidgetItem([self._label(self._folder_name(f.name, f.role), f.unread)])
                child.setData(0, FOLDER, (account.id, f.name))
                top.addChild(child)
        self.folders.blockSignals(False)
        self._select_scope(keep or ALL_INBOXES)

    @staticmethod
    def _label(name: str, unread: int) -> str:
        return f"{name}   {unread}" if unread else name

    @staticmethod
    def _folder_name(name: str, role: str) -> str:
        return {"inbox": _("Inbox"), "sent": _("Sent"), "archive": _("Archive"), "drafts": _("Drafts"),
                "trash": _("Trash"), "junk": _("Junk")}.get(role, name)

    def _current_scope(self):
        item = self.folders.currentItem()
        return item.data(0, FOLDER) if item else None

    def _select_scope(self, scope):
        def walk(item):
            if item.data(0, FOLDER) == scope:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found:
                    return found
        for i in range(self.folders.topLevelItemCount()):
            found = walk(self.folders.topLevelItem(i))
            if found:
                self.folders.setCurrentItem(found)
                return
        self.folders.setCurrentItem(self.folders.topLevelItem(0))

    # ---- the list ----

    def show_list(self):
        scope = self._current_scope() or ALL_INBOXES
        query = self.search.text()
        if scope == ALL_INBOXES:
            threads = self.service.threads(None, "INBOX", query)
            title = _("All inboxes")
        else:
            account_id, folder = scope
            threads = self.service.threads(account_id, folder, query)
            title = self.folders.currentItem().text(0).rsplit("   ", 1)[0]
        self.title.setText(_("Search") if query.strip() else title)
        unread = sum(t.unread for t in threads)
        self.subtitle.setText(_("{n} unread").format(n=unread) if unread else _("Nothing unread"))
        self.threads.blockSignals(True)
        self.threads.clear()
        for r in threads:
            item = QListWidgetItem()
            item.setData(THREAD, r)
            self.threads.addItem(item)
        self.threads.blockSignals(False)
        self._clear_reader()

    def _thread_picked(self, item: QListWidgetItem | None):
        if item is None:
            return self._clear_reader()
        r: ThreadRecord = item.data(THREAD)
        account_id, folder, uid = r.keys[-1]  # the newest message of the conversation
        self.load_images = False
        self._open(account_id, folder, uid)

    # ---- the reader ----

    def _open(self, account_id: int, folder: str, uid: int):
        try:
            m = self.service.open(account_id, folder, uid, self.load_images)
        except ApplicationError as e:
            QMessageBox.warning(self, APP_NAME, _(str(e)))
            return
        self._record = m
        self.subject.setText(m.subject)
        when = f"{m.sent.day} {m.sent.strftime('%b %Y')}, {m.sent.hour:02d}:{m.sent.minute:02d}"
        self.from_line.setText(f"{m.sender} <{m.sender_email}>  ·  {when}\n" + _("To: {to}").format(to=m.to))
        self.reader.setHtml(m.html)
        self.star_button.setToolTip(_("Unflag") if m.flagged else _("Flag this message"))
        blocked = m.blocked_images and not self.load_images
        self.notice.setText(_("{n} remote picture(s) not loaded, so the sender can't tell you opened this.")
                            .format(n=m.blocked_images) if blocked else "")
        self.load_button.setVisible(bool(blocked))
        self.refresh_folders_counts()

    def refresh_folders_counts(self):
        """Unread numbers change as messages are opened: redraw the tree without losing the place."""
        scope = self._current_scope()
        self.refresh_folders_quietly(scope)

    def refresh_folders_quietly(self, scope):
        self.folders.blockSignals(True)
        folders = {(f.account_id, f.name): f for f in self.service.folders()}

        def walk(item):
            key = item.data(0, FOLDER)
            if key and key[1] is not None and key in folders:
                f = folders[key]
                item.setText(0, self._label(self._folder_name(f.name, f.role), f.unread))
            if key == ALL_INBOXES:
                item.setText(0, self._label(_("All inboxes"), sum(f.unread for f in folders.values() if f.role == "inbox")))
            for i in range(item.childCount()):
                walk(item.child(i))
        for i in range(self.folders.topLevelItemCount()):
            walk(self.folders.topLevelItem(i))
        self.folders.blockSignals(False)

    def _clear_reader(self):
        self._record = None
        self.subject.setText("")
        self.from_line.setText("")
        self.notice.setText("")
        self.load_button.setVisible(False)
        self.reader.setHtml("")

    def _load_pictures(self):
        if self._record:
            self.load_images = True
            self._open(self._record.account_id, self._record.folder, self._record.uid)

    def _toggle_flag(self):
        if self._record:
            self.service.toggle_flag((self._record.account_id, self._record.folder, self._record.uid))
            current = self.threads.currentRow()
            self.show_list()
            self.threads.setCurrentRow(current)

    def _link_clicked(self, url: QUrl):
        """Show where a link really goes before leaving for it."""
        target = url.toString()
        answer = QMessageBox.question(self, APP_NAME, _("Open this link?\n\n{url}").format(url=target))
        if answer == QMessageBox.Yes:
            QDesktopServices.openUrl(url)

    # ---- fetching ----

    def sync(self):
        self.sync_button.setEnabled(False)
        try:
            report = self.service.sync()
            self.refresh_folders()
            self.statusBar().showMessage(_("{n} new message(s)").format(n=report.new), 4000)
        except ApplicationError as e:
            QMessageBox.warning(self, APP_NAME, str(e))
        finally:
            self.sync_button.setEnabled(True)
