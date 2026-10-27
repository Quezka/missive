"""The three panes: folders, conversations, and the message being read."""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta

from PySide6.QtCore import (
    QModelIndex, QObject, QRect, QRunnable, QSettings, QSize, Qt, QThread, QThreadPool, QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import (
    QActionGroup, QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QPainter, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME
from ..application.errors import ApplicationError
from ..application.records import DraftRecord, MessageRecord, ThreadRecord
from ..application.services import MailService
from . import icons, theme
from .account_dialog import AccountDialog
from .compose_dialog import ComposeDialog
from .i18n import _
from .views.common import Card, button, icon_button, label, primary_button

THREAD, HEADER = Qt.UserRole + 1, Qt.UserRole + 2
ALL_INBOXES = ("all", None)
SYNC_EVERY_MS = 5 * 60 * 1000
FOLDER_ICONS = {"inbox": "inbox", "sent": "send", "drafts": "edit", "archive": "archive", "trash": "trash",
                "junk": "alert", "": "folder"}
# Dark enough for white initials on any theme.
AVATAR_COLORS = ("#4b4bc8", "#1f8a5b", "#c4262c", "#b45309", "#0a5ad6", "#8a4bc8", "#0f8a7e", "#c02f8b")


def short_when(when: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if when.date() == now.date():
        return f"{when.hour:02d}:{when.minute:02d}"
    if (now.date() - when.date()).days < 7:
        return when.strftime("%a")
    return f"{when.day} {when.strftime('%b')}"


def bucket(when: datetime, now: datetime | None = None) -> str:
    """Which heading a conversation sits under in the list."""
    today = (now or datetime.now()).date()
    days = (today - when.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return "week" if days < 7 else "earlier"


def bucket_title(key: str) -> str:
    return {"today": _("Today"), "yesterday": _("Yesterday"), "week": _("Last 7 days"),
            "earlier": _("Earlier")}[key]


def initials(who: str) -> str:
    words = [w for w in who.replace(".", " ").replace("_", " ").replace("-", " ").split() if w[:1].isalnum()]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


_avatars: dict[tuple, QPixmap] = {}


def avatar(who: str, size: int, dpr: float = 1.0, identity: str = "") -> QPixmap:
    """A round avatar with the sender's initials, coloured by who they are: the same address, the same colour
    in the list and in the reader (`identity` is the address; without one the name is used)."""
    key = (who, identity, size, dpr)
    if key not in _avatars:
        seed = (identity or who).lower()
        color = AVATAR_COLORS[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(AVATAR_COLORS)]
        pm = QPixmap(int(size * dpr), int(size * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(0, 0, size, size)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(9, int(size * 0.38)))
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, initials(who))
        p.end()
        _avatars[key] = pm
    return _avatars[key]


class ThreadDelegate(QStyledItemDelegate):
    """One conversation (avatar, who, when, subject, start of the latest message) or a day heading."""

    HEIGHT, HEADING, AVATAR = 78, 30, 40

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.HEADING if index.data(HEADER) else self.HEIGHT)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        t = theme.current()
        heading = index.data(HEADER)
        if heading:
            p.save()
            font = QFont(option.font)
            font.setBold(True)
            font.setPointSizeF(max(7.5, font.pointSizeF() * 0.85))
            p.setFont(font)
            p.setPen(QColor(t.faint))
            p.drawText(option.rect.adjusted(20, 8, -10, 0), Qt.AlignLeft | Qt.AlignVCenter, heading.upper())
            p.restore()
            return
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
        unread = r.unread > 0
        dpr = option.widget.devicePixelRatioF() if option.widget else 1.0
        top = box.top() + (box.height() - self.AVATAR) // 2
        p.drawPixmap(box.left() + 10, top, avatar(r.sender or r.people or "?", self.AVATAR, dpr, r.sender_email))
        if unread:  # the unread dot sits on the avatar's corner
            p.setPen(QColor(t.sidebar if not selected else t.accent_soft))
            p.setBrush(QColor(t.accent))
            p.drawEllipse(box.left() + 10 + self.AVATAR - 11, top - 1, 12, 12)
        inner = box.adjusted(10 + self.AVATAR + 12, 9, -10, -6)
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
        line = bold if unread else base
        p.setFont(line)
        p.setPen(QColor(t.text))
        people = r.people + (f"  {r.count}" if r.count > 1 else "")
        p.drawText(QRect(inner.left(), inner.top(), inner.width() - wide - 10, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(line).elidedText(people, Qt.ElideRight, inner.width() - wide - 10))
        subject = ("⚑ " if r.flagged else "") + r.subject
        p.drawText(QRect(inner.left(), inner.top() + 20, inner.width(), 18), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(line).elidedText(subject, Qt.ElideRight, inner.width()))
        p.setFont(small)
        p.setPen(QColor(t.muted))
        p.drawText(QRect(inner.left(), inner.top() + 40, inner.width(), 16), Qt.AlignLeft | Qt.AlignVCenter,
                   QFontMetrics(small).elidedText(("📎 " if r.has_attachments else "") + r.snippet,
                                                  Qt.ElideRight, inner.width()))
        p.restore()


class NavButton(QToolButton):
    """A sidebar row: icon, name, and the unread count as a little pill on the right."""

    def __init__(self, text: str, icon_name: str, scope, parent=None):
        super().__init__(parent)
        self.scope = scope
        self.unread = 0
        self.setObjectName("nav")
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setStyleSheet("QToolButton { padding: 7px 44px 7px 10px; }")
        theme.set_icon(self, icon_name, "muted", "accent", 18)

    def set_unread(self, n: int):
        self.unread = n
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.unread <= 0:
            return
        t = theme.current()
        text = str(self.unread) if self.unread < 1000 else "999+"
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSizeF(max(7.5, font.pointSizeF() * 0.85))
        metrics = QFontMetrics(font)
        w, h = max(22, metrics.horizontalAdvance(text) + 14), metrics.height() + 2
        pill = QRect(self.width() - w - 10, (self.height() - h) // 2, w, h)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t.accent if self.isChecked() else t.accent_soft))
        p.drawRoundedRect(pill, h / 2, h / 2)
        p.setFont(font)
        p.setPen(QColor(t.on_accent if self.isChecked() else t.accent))
        p.drawText(pill, Qt.AlignCenter, text)
        p.end()


class _SyncJob(QObject):
    """Checks for new mail off the UI thread: the network can take minutes on a big mailbox."""

    progress = Signal(str)
    done = Signal(object, str)  # the check itself is over: (SyncReport or None, what went wrong or "")
    finished = Signal()  # and the newest letters have been downloaded too: the thread can end

    def __init__(self, service: MailService):
        super().__init__()
        self._service = service
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _report(self, account: str, folder: str, _new: int):
        self.progress.emit(_("Checking {name}…").format(name=f"{account} · {folder.rsplit('/', 1)[-1]}"))
        return not self._stop.is_set()

    def run(self):
        try:
            self.done.emit(self._service.sync(progress=self._report), "")
        except ApplicationError as e:
            self.done.emit(None, str(e))
            return self.finished.emit()
        except Exception as e:  # noqa: BLE001
            self.done.emit(None, f"{type(e).__name__}: {e}")
            return self.finished.emit()
        try:  # quietly, after the screen is already up to date: the newest letters then open instantly
            self._service.prefetch(stop=self._stop.is_set)
        except Exception:  # noqa: BLE001 (they will be fetched when opened)
            pass
        self.finished.emit()


class _OpenTask(QRunnable):
    """Opens a message that has to be fetched from the server, off the UI thread."""

    class Signals(QObject):
        done = Signal(int, object, str)  # (which request, MessageRecord or None, what went wrong or "")

    def __init__(self, service: MailService, key: tuple[int, str, int], load_images: bool, seq: int):
        super().__init__()
        self.signals = self.Signals()
        self._service, self._key, self._load_images, self._seq = service, key, load_images, seq

    def run(self):
        try:
            result = (self._service.open(*self._key, self._load_images), "")
        except ApplicationError as e:
            result = (None, str(e))
        except Exception as e:  # noqa: BLE001
            result = (None, f"{type(e).__name__}: {e}")
        try:
            self.signals.done.emit(self._seq, *result)
        except RuntimeError:  # the window is gone and took the receiver with it: nobody is waiting
            pass


class _SendTask(QRunnable):
    """Sends a message off the UI thread; the draft comes back with the answer so nothing typed is ever lost."""

    class Signals(QObject):
        done = Signal(object, str)  # (the DraftRecord, what went wrong or "")

    def __init__(self, service: MailService, draft: DraftRecord):
        super().__init__()
        self.signals = self.Signals()
        self._service, self._draft = service, draft

    def run(self):
        try:
            self._service.send(self._draft)
            problem = ""
        except ApplicationError as e:
            problem = str(e)
        except Exception as e:  # noqa: BLE001
            problem = f"{type(e).__name__}: {e}"
        try:
            self.signals.done.emit(self._draft, problem)
        except RuntimeError:  # the window is gone
            pass


class MainWindow(QMainWindow):
    SEND_DELAY = 8  # seconds to change your mind after pressing Send

    def __init__(self, service: MailService, auto_sync: bool = False):
        super().__init__()
        self.service = service
        self.load_images = False
        self._record: MessageRecord | None = None
        self._scope = ALL_INBOXES
        self.nav: dict[tuple, NavButton] = {}
        self._thread: QThread | None = None
        self._job: _SyncJob | None = None
        self._open_seq = 0  # numbers the open requests, so a slow answer to an old click is ignored
        self._open_tasks: set[_OpenTask] = set()
        self._composers: list[ComposeDialog] = []
        self._send_tasks: set[_SendTask] = set()
        self._pending: tuple[DraftRecord, int] | None = None  # (message waiting to go out, seconds left)
        self.setWindowTitle(APP_NAME)
        self.resize(1240, 780)
        self.setMinimumSize(720, 460)

        # ---- sidebar
        self.sidebar = QFrame(objectName="sidebar")
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(300)
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(28, 28)
        brand.addWidget(self.brand_icon)
        brand.addWidget(QLabel(APP_NAME, objectName="brand"))
        brand.addStretch()
        self.nav_box = QVBoxLayout()
        self.nav_box.setSpacing(2)
        holder = QWidget()
        holder.setObjectName("navHolder")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addLayout(self.nav_box)
        holder_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(holder)
        self.add_account_button = button(_("Add account"), "plus")
        self.add_account_button.clicked.connect(self.add_account)
        self.menu_button = icon_button("settings", _("Settings"))
        self.menu_button.clicked.connect(self._show_menu)
        self.status = label("", "hint")
        self.status.setWordWrap(True)
        foot = QHBoxLayout()
        foot.addWidget(self.add_account_button, 1)
        foot.addWidget(self.menu_button)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(10, 14, 10, 10)
        side.setSpacing(10)
        self.compose_button = primary_button(_("New message"), "edit")
        self.compose_button.clicked.connect(self.compose)
        side.addLayout(brand)
        side.addWidget(self.compose_button)
        side.addWidget(scroll, 1)
        side.addWidget(self.status)
        side.addLayout(foot)

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
        head.addWidget(self.sync_button, 0, Qt.AlignTop)
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)  # indeterminate: we know it's working, not how far it is
        self.busy.setTextVisible(False)
        self.busy.setFixedHeight(3)
        self.busy.hide()
        self.threads = QListWidget(objectName="threads")
        self.threads.setItemDelegate(ThreadDelegate(self.threads))
        self.threads.setMouseTracking(True)
        self.threads.setFrameShape(QFrame.NoFrame)
        self.threads.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.threads.currentItemChanged.connect(lambda cur, _prev: self._thread_picked(cur))
        self.empty_list = label(_("Nothing here yet"), "hint")
        self.empty_list.setAlignment(Qt.AlignCenter)
        self.empty_list.hide()
        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(14, 18, 8, 12)
        middle_layout.setSpacing(10)
        middle_layout.addLayout(head)
        middle_layout.addWidget(self.search)
        middle_layout.addWidget(self.busy)
        middle_layout.addWidget(self.threads, 1)
        middle_layout.addWidget(self.empty_list, 1)

        # ---- reader
        self.subject = QLabel(objectName="pageTitle", wordWrap=True)
        self.subject.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sender_avatar = QLabel()
        self.sender_avatar.setFixedSize(40, 40)
        self.sender_name = QLabel(objectName="sheetTitle")
        self.sender_name.setStyleSheet("font-size: 11pt;")
        self.sender_email = label("", "muted")
        self.sender_when = label("", "muted")
        self.from_line = label("", "muted")  # "To: …"
        self.from_line.setWordWrap(True)
        self.notice = QLabel(wordWrap=True)
        self.load_button = button(_("Load pictures"), "image")
        self.load_button.clicked.connect(self._load_pictures)
        self.banner = QFrame(objectName="banner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(12, 8, 8, 8)
        banner_row.addWidget(self.notice, 1)
        banner_row.addWidget(self.load_button)
        self.banner.hide()
        self.star_button = icon_button("star", _("Flag this message"), checkable=True)
        self.star_button.clicked.connect(self._toggle_flag)
        self.reply_button = icon_button("reply", _("Reply"))
        self.reply_all_button = icon_button("reply-all", _("Reply to all"))
        self.forward_button = icon_button("forward", _("Forward"))
        self.reply_button.clicked.connect(lambda: self.reply(False))
        self.reply_all_button.clicked.connect(lambda: self.reply(True))
        self.forward_button.clicked.connect(self.forward)
        self.reader = QTextBrowser()
        self.reader.setOpenLinks(False)
        self.reader.setFrameShape(QFrame.NoFrame)
        self.reader.anchorClicked.connect(self._link_clicked)
        self.reader.setPlaceholderText(_("Select a message to read it."))
        sender = QVBoxLayout()
        sender.setSpacing(0)
        sender.addWidget(self.sender_name)
        sender.addWidget(self.sender_email)
        who = QHBoxLayout()
        who.setSpacing(12)
        who.addWidget(self.sender_avatar, 0, Qt.AlignTop)
        who.addLayout(sender, 1)
        who.addWidget(self.sender_when, 0, Qt.AlignTop)
        top = QHBoxLayout()
        top.addWidget(self.subject, 1)
        for tool in (self.reply_button, self.reply_all_button, self.forward_button, self.star_button):
            top.addWidget(tool, 0, Qt.AlignTop)
        rule = QFrame(objectName="rule")
        rule.setFixedHeight(1)
        message = QWidget()
        message_layout = QVBoxLayout(message)
        message_layout.setContentsMargins(22, 20, 22, 14)
        message_layout.setSpacing(12)
        message_layout.addLayout(top)
        message_layout.addLayout(who)
        message_layout.addWidget(self.from_line)
        message_layout.addWidget(self.banner)
        message_layout.addWidget(rule)
        message_layout.addWidget(self.reader, 1)
        self.empty_icon = QLabel(alignment=Qt.AlignCenter)
        self.empty_text = label(_("Select a message to read it."), "hint")
        self.empty_text.setAlignment(Qt.AlignCenter)
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_icon)
        empty_layout.addWidget(self.empty_text)
        self.reader_pages = QStackedWidget()
        self.reader_pages.addWidget(empty)
        self.reader_pages.addWidget(message)
        card = Card(padding=0)
        card.add(self.reader_pages, 1)
        self.undo_text = QLabel(wordWrap=True)
        self.undo_button = button(_("Undo"))
        self.undo_button.clicked.connect(self._undo_send)
        self.undo_bar = QFrame(objectName="banner")
        undo_row = QHBoxLayout(self.undo_bar)
        undo_row.setContentsMargins(14, 8, 8, 8)
        undo_row.addWidget(self.undo_text, 1)
        undo_row.addWidget(self.undo_button)
        self.undo_bar.hide()
        self._undo_timer = QTimer(self)
        self._undo_timer.setInterval(1000)
        self._undo_timer.timeout.connect(self._undo_tick)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 18, 16, 16)
        right_layout.addWidget(self.undo_bar)
        right_layout.addWidget(card)

        self.split = QSplitter(Qt.Horizontal)
        for w in (self.sidebar, middle, right):
            self.split.addWidget(w)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 2)
        self.split.setChildrenCollapsible(False)
        sizes = QSettings().value("window/split")
        self.split.setSizes([int(x) for x in sizes] if sizes and len(sizes) == 3 else [230, 410, 600])
        self.split.splitterMoved.connect(lambda *_a: QSettings().setValue("window/split", self.split.sizes()))
        # No account yet: a welcome page instead of three empty panes.
        self.welcome = QWidget()
        welcome = QVBoxLayout(self.welcome)
        welcome.setAlignment(Qt.AlignCenter)
        welcome.setSpacing(12)
        self.welcome_icon = QLabel(alignment=Qt.AlignCenter)
        headline = QLabel(_("Welcome to Missive"), objectName="pageTitle", alignment=Qt.AlignCenter)
        intro = label(_("Add your mail account to start. Missive reads your mail without changing it, and sends "
                        "only what you write yourself."), "muted")
        intro.setWordWrap(True)
        intro.setAlignment(Qt.AlignCenter)
        intro.setMaximumWidth(440)
        providers = label(_("Gmail, Outlook, iCloud and any other IMAP mailbox"), "hint")
        providers.setAlignment(Qt.AlignCenter)
        self.welcome_button = primary_button(_("Add a mail account"), "plus")
        self.welcome_button.clicked.connect(self.add_account)
        welcome.addWidget(self.welcome_icon, 0, Qt.AlignHCenter)
        for w in (headline, intro):
            welcome.addWidget(w, 0, Qt.AlignHCenter)
        welcome.addSpacing(6)
        welcome.addWidget(self.welcome_button, 0, Qt.AlignHCenter)
        welcome.addWidget(providers, 0, Qt.AlignHCenter)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.split)
        self.pages.addWidget(self.welcome)
        self.setCentralWidget(self.pages)

        for keys, action in ((("Ctrl+R", "F5"), self.sync), (("Ctrl+F",), self.search.setFocus)):
            for key in keys:
                QShortcut(QKeySequence(key), self, activated=action)
        theme.themed(self._restyle)
        self.refresh_folders()
        self._clear_reader()
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.sync)
        if auto_sync:
            self._auto_timer.start(SYNC_EVERY_MS)
            QTimer.singleShot(400, self._first_sync)

    def _first_sync(self):
        if self.service.accounts():
            self.sync()

    # ---- look ----

    def _restyle(self, t):
        self.threads.setStyleSheet("QListWidget#threads { background: transparent; border: none; }")
        self.reader.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.reader.document().setDefaultStyleSheet(
            f"a {{ color: {t.accent}; }} blockquote {{ color: {t.muted}; border-left: 3px solid {t.border}; "
            f"margin-left: 0; padding-left: 10px; }}")
        self.banner.setStyleSheet(f"QFrame#banner {{ background: {t.accent_soft}; border-radius: 9px; }}")
        self.undo_bar.setStyleSheet(f"QFrame#banner {{ background: {t.accent_soft}; border-radius: 9px; }}")
        self.notice.setStyleSheet(f"color: {t.text};")
        self.undo_text.setStyleSheet(f"color: {t.text};")
        self.busy.setStyleSheet(
            f"QProgressBar {{ background: transparent; border: none; }}"
            f"QProgressBar::chunk {{ background: {t.accent}; border-radius: 1px; }}")
        self.brand_icon.setPixmap(icons.pixmap("mail", t.accent, 24, 2.2))
        self.empty_icon.setPixmap(icons.pixmap("mail", t.border, 64, 1.4))
        self.welcome_icon.setPixmap(icons.pixmap("mail", t.accent, 72, 1.6))
        self.search.removeAction(self._search_action) if getattr(self, "_search_action", None) else None
        self._search_action = self.search.addAction(icons.icon("search", t.faint, size=16), QLineEdit.LeadingPosition)
        for rule in self.findChildren(QFrame, "rule"):
            rule.setStyleSheet(f"QFrame#rule {{ background: {t.border}; border: none; }}")

    # ---- the sidebar ----

    def refresh_folders(self):
        accounts = self.service.accounts()
        folders = self.service.folders()
        while self.nav_box.count():
            item = self.nav_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.nav = {}
        unread_all = sum(f.unread for f in folders if f.role == "inbox")
        self._add_nav(_("All inboxes"), "inbox", ALL_INBOXES, unread_all)
        for account in accounts:
            section = QLabel(f'<span style="color:{account.color}">●</span>&nbsp; {account.name.upper()}',
                             objectName="sidebarSection")
            section.setToolTip(account.address)
            self.nav_box.addSpacing(10)
            self.nav_box.addWidget(section)
            for f in (f for f in folders if f.account_id == account.id):
                self._add_nav(self._folder_name(f.title or f.name, f.role), FOLDER_ICONS.get(f.role, "folder"),
                              (account.id, f.name), f.unread)
        if self._scope not in self.nav:
            self._scope = ALL_INBOXES
        self.nav[self._scope].setChecked(True)
        self.pages.setCurrentWidget(self.split if accounts else self.welcome)
        self.show_list(preserve=True)

    def _add_nav(self, text: str, icon_name: str, scope, unread: int):
        row = NavButton(text, icon_name, scope)
        row.set_unread(unread)
        row.clicked.connect(lambda _checked=False, s=scope: self._select_scope(s))
        self.nav[scope] = row
        self.nav_box.addWidget(row)

    @staticmethod
    def _folder_name(name: str, role: str) -> str:
        return {"inbox": _("Inbox"), "sent": _("Sent"), "archive": _("Archive"), "drafts": _("Drafts"),
                "trash": _("Trash"), "junk": _("Junk")}.get(role, name)

    def _current_scope(self):
        return self._scope

    def _select_scope(self, scope):
        if scope not in self.nav:
            scope = ALL_INBOXES
        self._scope = scope
        for key, row in self.nav.items():
            row.setChecked(key == scope)
        self.show_list()

    def refresh_folders_counts(self):
        """Unread numbers change as messages are opened: redraw the counts without losing the place."""
        folders = {(f.account_id, f.name): f for f in self.service.folders()}
        for scope, row in self.nav.items():
            if scope == ALL_INBOXES:
                row.set_unread(sum(f.unread for f in folders.values() if f.role == "inbox"))
            elif scope in folders:
                row.set_unread(folders[scope].unread)

    # ---- the list ----

    def show_list(self, preserve: bool = False):
        """Fill the conversation list. With `preserve` (a background refresh) the message being read stays open."""
        scope = self._scope
        query = self.search.text()
        if scope == ALL_INBOXES:
            threads = self.service.threads(None, "INBOX", query)
            title = _("All inboxes")
        else:
            account_id, folder = scope
            threads = self.service.threads(account_id, folder, query)
            title = self.nav[scope].text()
        self.title.setText(_("Search") if query.strip() else title)
        unread = sum(t.unread for t in threads)
        self.subtitle.setText(_("{n} unread").format(n=unread) if unread else _("Nothing unread"))
        keep = self._record and (self._record.account_id, self._record.folder, self._record.uid)
        self.threads.blockSignals(True)
        self.threads.clear()
        now, last, reselect = datetime.now(), None, None
        for r in threads:
            key = bucket(r.latest, now)
            if key != last:
                last = key
                heading = QListWidgetItem()
                heading.setData(HEADER, bucket_title(key))
                heading.setFlags(Qt.NoItemFlags)
                self.threads.addItem(heading)
            item = QListWidgetItem()
            item.setData(THREAD, r)
            self.threads.addItem(item)
            if keep and keep in r.keys:
                reselect = item
        self.threads.blockSignals(False)
        self.threads.setVisible(bool(threads))
        self.empty_list.setVisible(not threads)
        if preserve and reselect is not None:
            self.threads.blockSignals(True)
            self.threads.setCurrentItem(reselect)
            self.threads.blockSignals(False)
        else:
            self._clear_reader()

    def _thread_picked(self, item: QListWidgetItem | None):
        r: ThreadRecord | None = item.data(THREAD) if item is not None else None
        if r is None:
            return self._clear_reader()
        account_id, folder, uid = r.keys[-1]  # the newest message of the conversation
        self.load_images = False
        self._open(account_id, folder, uid, pending=r)

    # ---- the reader ----

    def _open(self, account_id: int, folder: str, uid: int, pending: ThreadRecord | None = None):
        """Show a message. When its text is already here it appears at once; otherwise it is fetched in the
        background while the reader says so, and a newer click makes the older answer irrelevant."""
        self._open_seq += 1
        key = (account_id, folder, uid)
        if not self.service.needs_fetch(*key):
            try:
                return self._show(self.service.open(*key, self.load_images))
            except ApplicationError as e:
                return self._open_failed(str(e))
        self._record = None
        if pending is not None:
            self.subject.setText(pending.subject)
            self.sender_avatar.setPixmap(avatar(pending.sender or pending.people or "?", 40,
                                                self.devicePixelRatioF(), pending.sender_email))
            self.sender_name.setText(pending.sender or pending.people)
            self.sender_email.setText(pending.sender_email)
        if pending is None:
            self.sender_email.setText("")
        self.sender_when.setText("")
        self.from_line.setText("")
        self.banner.hide()
        self.reader.setHtml("")
        self.reader.setPlaceholderText(_("Loading…"))
        self.reader_pages.setCurrentIndex(1)
        self._set_reply_enabled(False)
        task = _OpenTask(self.service, key, self.load_images, self._open_seq)
        self._open_tasks.add(task)
        task.signals.done.connect(lambda seq, record, problem, t=task: self._opened(seq, record, problem, t))
        QThreadPool.globalInstance().start(task)

    def _opened(self, seq: int, record: MessageRecord | None, problem: str, task: _OpenTask):
        self._open_tasks.discard(task)
        if seq != self._open_seq:
            return  # the user has clicked something else since
        if record is None:
            return self._open_failed(problem)
        self._show(record)

    def _open_failed(self, problem: str):
        self.reader.setPlaceholderText(_("Couldn't load this message: {why}").format(why=_(problem)))

    def _show(self, m: MessageRecord):
        self._record = m
        self.reader.setPlaceholderText(_("Select a message to read it."))
        self.subject.setText(m.subject)
        self.sender_avatar.setPixmap(avatar(m.sender, 40, self.devicePixelRatioF(), m.sender_email))
        self.sender_name.setText(m.sender)
        self.sender_email.setText(m.sender_email)
        self.sender_when.setText(f"{m.sent.day} {m.sent.strftime('%b %Y')}, {m.sent.hour:02d}:{m.sent.minute:02d}")
        self.from_line.setText(_("To: {to}").format(to=m.to))
        self.reader.setHtml(m.html)
        self.star_button.setToolTip(_("Unflag") if m.flagged else _("Flag this message"))
        self.star_button.setChecked(m.flagged)
        blocked = m.blocked_images and not self.load_images
        self.notice.setText(_("{n} remote picture(s) not loaded, so the sender can't tell you opened this.")
                            .format(n=m.blocked_images) if blocked else "")
        self.load_button.setVisible(bool(blocked))
        self.banner.setVisible(bool(blocked))
        self.reader_pages.setCurrentIndex(1)
        self._set_reply_enabled(True)
        self.refresh_folders_counts()

    def _set_reply_enabled(self, on: bool):
        for tool in (self.reply_button, self.reply_all_button, self.forward_button):
            tool.setEnabled(on and self.service.can_send())

    def _clear_reader(self):
        self._record = None
        self.subject.setText("")
        self.sender_name.setText("")
        self.sender_email.setText("")
        self.sender_when.setText("")
        self.from_line.setText("")
        self.notice.setText("")
        self.load_button.setVisible(False)
        self.banner.setVisible(False)
        self.reader.setHtml("")
        self.reader_pages.setCurrentIndex(0)
        self._set_reply_enabled(False)

    def _load_pictures(self):
        if self._record:
            self.load_images = True
            self._open(self._record.account_id, self._record.folder, self._record.uid)

    def _toggle_flag(self):
        if self._record:
            self.service.toggle_flag((self._record.account_id, self._record.folder, self._record.uid))
            self.show_list(preserve=True)
            self.star_button.setChecked(self.service.is_flagged(
                (self._record.account_id, self._record.folder, self._record.uid)))

    def _link_clicked(self, url: QUrl):
        """Show where a link really goes before leaving for it."""
        target = url.toString()
        answer = QMessageBox.question(self, APP_NAME, _("Open this link?\n\n{url}").format(url=target))
        if answer == QMessageBox.Yes:
            QDesktopServices.openUrl(url)

    # ---- writing ----

    def _open_composer(self, draft: DraftRecord):
        dialog = ComposeDialog(self.service, draft, self)
        dialog.send_requested.connect(self._queue_send)
        dialog.destroyed.connect(lambda _o=None, d=dialog: self._composers.remove(d) if d in self._composers else None)
        self._composers.append(dialog)
        dialog.show()
        return dialog

    def compose(self):
        """A new message from the account being looked at (or the first one)."""
        scope = self._scope
        try:
            self._open_composer(self.service.new_draft(scope[0] if scope != ALL_INBOXES else None))
        except ApplicationError as e:
            QMessageBox.warning(self, APP_NAME, _(str(e)))

    def _key(self):
        r = self._record
        return (r.account_id, r.folder, r.uid) if r else None

    def reply(self, everyone: bool):
        if self._key():
            self._open_composer(self.service.reply_draft(self._key(), everyone))

    def forward(self):
        if self._key():
            self._open_composer(self.service.forward_draft(self._key()))

    def _queue_send(self, draft: DraftRecord):
        """Pressing Send starts a countdown, so a slip can still be taken back; then the message goes out."""
        if self._pending is not None:  # one already waiting: it goes now, this one takes its place
            self._send_now(self._pending[0])
        self._pending = (draft, self.SEND_DELAY)
        self.undo_bar.show()
        self._undo_tick(first=True)
        if self.SEND_DELAY <= 0:
            return self._undo_tick()
        self._undo_timer.start()

    def _undo_tick(self, first: bool = False):
        if self._pending is None:
            return
        draft, left = self._pending
        if not first:
            left -= 1
            self._pending = (draft, left)
        if left <= 0:
            self._undo_timer.stop()
            self._pending = None
            self.undo_bar.hide()
            return self._send_now(draft)
        self.undo_text.setText(_("Sending to {to} in {n} s…").format(to=draft.to.split(",")[0].strip() or draft.cc,
                                                                    n=left))

    def _undo_send(self):
        """Take the message back: the compose window comes back with everything in it."""
        if self._pending is None:
            return
        draft, _left = self._pending
        self._pending = None
        self._undo_timer.stop()
        self.undo_bar.hide()
        self._open_composer(draft)
        self.status.setText(_("Not sent"))

    def _send_now(self, draft: DraftRecord):
        self.status.setText(_("Sending…"))
        task = _SendTask(self.service, draft)
        self._send_tasks.add(task)
        task.signals.done.connect(lambda d, problem, t=task: self._sent(d, problem, t))
        QThreadPool.globalInstance().start(task)

    def _sent(self, draft: DraftRecord, problem: str, task: _SendTask):
        self._send_tasks.discard(task)
        if not problem:
            self.status.setText(_("Message sent"))
            return
        self.status.setText(_("Couldn't send the message"))
        self._open_composer(draft)  # what was typed is never lost
        QMessageBox.warning(self, APP_NAME, _("The message wasn't sent:\n\n{why}").format(why=_(problem)))

    # ---- accounts and settings ----

    def add_account(self):
        dialog = AccountDialog(self.service, self)
        if dialog.exec() == AccountDialog.Accepted and dialog.added:
            self.refresh_folders()
            self.sync()

    def contextMenuEvent(self, event):  # right-click on an account's section title removes the account
        pass

    def _show_menu(self):
        menu = QMenu(self)
        manager = theme.manager()
        look = menu.addMenu(_("Appearance"))
        group = QActionGroup(look)
        for mode, text in (("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))):
            action = look.addAction(text)
            action.setCheckable(True)
            action.setChecked(manager.mode == mode)
            action.triggered.connect(lambda _c=False, m=mode: manager.set_mode(m))
            group.addAction(action)
        contrast = menu.addAction(_("High contrast (black and white, thick lines)"))
        contrast.setCheckable(True)
        contrast.setChecked(manager.contrast)
        contrast.toggled.connect(manager.set_contrast)
        accounts = self.service.accounts()
        if accounts:
            menu.addSeparator()
            for account in accounts:
                remove = menu.addAction(_("Remove {name}…").format(name=account.name))
                remove.triggered.connect(lambda _c=False, a=account.id: self.remove_account(a))
        menu.exec(self.menu_button.mapToGlobal(self.menu_button.rect().topRight()))

    def remove_account(self, account_id: int):
        name = next((a.name for a in self.service.accounts() if a.id == account_id), "")
        answer = QMessageBox.question(self, APP_NAME, _("Remove {name} from Missive?\n\nIts messages are forgotten "
                                      "here and its password is deleted. Nothing changes on the mail server.")
                                      .format(name=name))
        if answer == QMessageBox.Yes:
            self.service.remove_account(account_id)
            self._scope = ALL_INBOXES
            self.refresh_folders()

    # ---- fetching ----

    def sync(self):
        """Check for new mail on a worker thread; the window stays usable and shows what it is doing."""
        if self._thread is not None or not self.service.accounts():
            return
        self.sync_button.setEnabled(False)
        self.busy.show()
        self.status.setText(_("Checking for new mail…"))
        self._thread = QThread(self)
        self._job = _SyncJob(self.service)
        self._job.moveToThread(self._thread)
        self._thread.started.connect(self._job.run)
        self._job.progress.connect(self.status.setText)
        self._job.done.connect(self._synced)  # methods of this window: delivered on the UI thread
        self._job.finished.connect(self._stop_sync)
        self._thread.start()

    @Slot()
    def _stop_sync(self):
        if self._thread is not None:
            self._job.stop()
            self._thread.quit()
            self._thread.wait(15000)
            self._thread = self._job = None

    @Slot(object, str)
    def _synced(self, report, problem: str):
        self.busy.hide()
        self.sync_button.setEnabled(True)
        self.refresh_folders()
        if problem:
            self.status.setText(_("Couldn't check for new mail"))
            self.status.setToolTip(_(problem))
            QMessageBox.warning(self, APP_NAME, _(problem))
            return
        now = datetime.now()
        self.status.setToolTip("\n".join(report.problems))
        if report.problems:
            self.status.setText(_("Some folders couldn't be read"))
        elif report.new:
            self.status.setText(_("{n} new message(s)").format(n=report.new))
        else:
            self.status.setText(_("Checked at {time}").format(time=f"{now.hour:02d}:{now.minute:02d}"))

    def closeEvent(self, event):
        self._auto_timer.stop()
        self._open_seq += 1  # whatever is still loading is no longer wanted
        if self._pending is not None:  # Send was pressed: closing the window doesn't take it back
            draft, _left = self._pending
            self._pending = None
            self._undo_timer.stop()
            self._send_now(draft)
        self._stop_sync()
        QThreadPool.globalInstance().waitForDone(5000)
        super().closeEvent(event)
