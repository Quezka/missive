import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402

from missive.presentation.main_window import THREAD, MainWindow  # noqa: E402
from missive.presentation.qt_app import create_application  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return create_application(["test"])


@pytest.fixture
def window(app, service):
    w = MainWindow(service)
    w.show()
    yield w
    w.close()


def titles(window):
    return [i.data(THREAD).subject for i in items(window)]


def items(window):
    """The conversations in the list (the day headings between them aren't conversations)."""
    return [window.threads.item(i) for i in range(window.threads.count()) if window.threads.item(i).data(THREAD)]


def row_of(window, subject):
    return next(i for i in range(window.threads.count())
                if window.threads.item(i).data(THREAD) and window.threads.item(i).data(THREAD).subject == subject)


def headings(window):
    from missive.presentation.main_window import HEADER
    return [window.threads.item(i).data(HEADER) for i in range(window.threads.count())
            if window.threads.item(i).data(HEADER)]


def test_the_sidebar_lists_the_unified_inbox_then_each_account_with_its_folders(window):
    assert list(window.nav)[0] == ("all", None)
    assert window.nav[("all", None)].text() == "All inboxes" and window.nav[("all", None)].unread == 7
    assert window.nav[("all", None)].isChecked()
    accounts = {a.id for a in window.service.accounts()}
    assert {scope[0] for scope in window.nav if scope[0] != "all"} == accounts
    assert any(row.text() == "Inbox" and row.unread for scope, row in window.nav.items() if scope[0] != "all")
    assert "ER diagram homework" in titles(window) and "Dinner on Saturday?" in titles(window)


def test_conversations_sit_under_day_headings(window):
    assert headings(window) and headings(window)[0] in ("Today", "Yesterday", "Last 7 days", "Earlier")
    assert window.threads.item(0).data(THREAD) is None  # the first row is a heading, which can't be picked
    assert not window.threads.item(0).flags() & Qt.ItemIsSelectable


def test_picking_a_conversation_shows_the_newest_message_clean_and_marks_it_read(window, app):
    window.threads.setCurrentRow(row_of(window, "ER diagram homework"))
    assert window.subject.text() == "ER diagram homework"  # the conversation's subject is there at once
    _settle(app, lambda: window._record is not None)
    assert window.subject.text() == "Re: ER diagram homework"
    assert "Both are fine" in window.reader.toPlainText()
    assert window.sender_name.text() and window.sender_email.text() and window.reader_pages.currentIndex() == 1
    assert next(t for t in window.service.threads(None, "INBOX") if t.subject == "ER diagram homework").unread == 1


def test_remote_pictures_stay_out_until_asked_for(window, app, monkeypatch):
    asked = []
    monkeypatch.setattr(type(window.reader), "_fetch", lambda self, url, generation: asked.append(url))  # no real network
    thread = next(t for t in window.service.threads(None, "INBOX") if t.subject == "ER diagram homework")
    window._open(*thread.keys[0])
    _settle(app, lambda: window._record is not None)
    assert "not loaded" in window.notice.text() and not window.banner.isHidden()
    assert "tracker.example" not in window.reader.toHtml() and asked == []  # nothing was fetched yet
    window.load_button.click()
    assert window.notice.text() == "" and window.banner.isHidden()
    assert asked == ["https://tracker.example/pixel.gif"]  # asking is what lets the pictures be fetched


def test_search_replaces_the_list_and_clearing_it_brings_it_back(window):
    all_titles = titles(window)
    window.search.setText("pizza")
    assert titles(window) == ["Dinner on Saturday?"] and window.title.text() == "Search"
    window.search.clear()
    assert titles(window) == all_titles


def test_an_empty_search_says_there_is_nothing_and_an_unpicked_reader_shows_the_empty_state(window):
    window.search.setText("zzzz-nothing-matches")
    assert titles(window) == [] and not window.empty_list.isHidden() and window.threads.isHidden()
    assert window.reader_pages.currentIndex() == 0


def test_flagging_marks_the_conversation_and_checking_mail_runs_in_the_background(window, app):
    window.threads.setCurrentRow(row_of(window, "Dinner on Saturday?"))
    _settle(app, lambda: window._record is not None)
    key = (window._record.account_id, window._record.folder, window._record.uid)
    before = window.service.is_flagged(key)  # the demo's dinner invitation starts flagged
    window.star_button.click()
    assert window.service.is_flagged(key) is (not before) and window.star_button.isChecked() is (not before)
    window.sync_button.click()
    _settle(app, lambda: window.sync_button.isEnabled() and window._thread is None)
    assert window.sync_button.isEnabled() and window.busy.isHidden() and not window.grab().isNull()
    assert window.status.text()  # "Checked at …" or the number of new messages


def test_every_folder_can_be_opened(window):
    for scope in list(window.nav):
        window._select_scope(scope)
        assert window.nav[scope].isChecked() and sum(r.isChecked() for r in window.nav.values()) == 1
        assert window.title.text()


def test_the_window_has_a_menu_for_appearance_and_removing_accounts(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMenu
    seen = []

    def look():
        menu = next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w.isVisible())
        seen.extend(a.text() for a in menu.actions())
        menu.close()
    QTimer.singleShot(200, look)
    window._show_menu()
    assert "Appearance" in seen and any(t.startswith("Remove ") for t in seen)


def _settle(app, until, seconds=10):
    import time
    end = time.time() + seconds
    while time.time() < end and not until():
        app.processEvents()
        time.sleep(0.01)


def test_with_no_account_a_welcome_page_leads_to_account_setup(app):
    from missive.application.services import MailService
    from missive.infrastructure.demo_source import DemoSource
    from missive.infrastructure.passwords import MemoryPasswords
    from missive.infrastructure.sqlite_store import SqliteStore
    service = MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords())
    w = MainWindow(service)
    w.show()
    assert w.pages.currentWidget() is w.welcome
    from missive.presentation.account_dialog import AccountDialog
    dialog = AccountDialog(service, w)
    assert not dialog.add_button.isEnabled()  # nothing typed yet
    dialog.address.setText("me@libero.it")
    dialog.password.setText("secret")
    assert dialog.add_button.isEnabled() and dialog.draft().host == "imapmail.libero.it"
    assert "app password" not in dialog.hint.text()
    dialog.address.setText("me@gmail.com")
    assert "app password" in dialog.hint.text()
    dialog.address.setText("me@outlook.com")  # Microsoft only takes OAuth, and this app has no client ID
    assert dialog.auth() == "microsoft" and not dialog.add_button.isEnabled() and "client ID" in dialog.hint.text()
    assert dialog.draft().host == "outlook.office365.com"
    dialog.address.setText("me@libero.it")
    assert dialog.auth() == "password" and dialog.draft().host == "imapmail.libero.it"
    dialog.add_button.click()  # checks on a worker thread, then saves on this one
    _settle(app, lambda: dialog.added is not None)
    assert dialog.added is not None and dialog.added.address == "me@libero.it"
    w.refresh_folders()
    assert w.pages.currentWidget() is w.split
    w.close()


def test_a_wrong_password_shows_the_server_reason_and_adds_nothing(app):
    from missive.application.errors import SourceError
    from missive.application.services import MailService
    from missive.infrastructure.demo_source import DemoSource
    from missive.infrastructure.passwords import MemoryPasswords
    from missive.infrastructure.sqlite_store import SqliteStore
    from missive.presentation.account_dialog import AccountDialog

    class Refusing(DemoSource):
        def check(self, account, password):
            raise SourceError("Home: [AUTHENTICATIONFAILED] Invalid credentials")
    service = MailService(SqliteStore(":memory:"), Refusing(), MemoryPasswords())
    dialog = AccountDialog(service)
    dialog.address.setText("me@libero.it")
    dialog.password.setText("wrong")
    dialog.add_button.click()
    _settle(app, lambda: not dialog.error.isHidden())
    assert "AUTHENTICATIONFAILED" in dialog.error.text() and service.accounts() == []
    assert dialog.add_button.isEnabled() and dialog.result() == 0


def _oauth_dialog(app, oauth, address="me@outlook.com"):
    from missive.application.services import MailService
    from missive.infrastructure.demo_source import DemoSource
    from missive.infrastructure.passwords import MemoryPasswords
    from missive.infrastructure.sqlite_store import SqliteStore
    from missive.presentation.account_dialog import AccountDialog
    service = MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords(), oauth)
    dialog = AccountDialog(service)
    dialog.address.setText(address)
    return service, dialog


def test_signing_in_with_microsoft_needs_no_password_and_keeps_the_token(app):
    from tests.test_accounts import FakeOAuth
    service, dialog = _oauth_dialog(app, FakeOAuth())
    assert dialog.auth() == "microsoft" and not dialog.form.isRowVisible(dialog.password)
    assert dialog.add_button.text() == "Sign in with Microsoft" and dialog.add_button.isEnabled()
    dialog.add_button.click()
    _settle(app, lambda: dialog.added is not None)
    assert dialog.added.address == "me@outlook.com"
    stored = service._store.accounts()[0]
    assert stored.auth == "microsoft" and service._passwords.get(stored.id) == "refresh-for-microsoft"


def test_gmail_defaults_to_the_app_password_until_google_sign_in_is_set_up(app):
    from tests.test_accounts import FakeOAuth
    _, plain = _oauth_dialog(app, FakeOAuth(configured=()), "me@gmail.com")
    assert plain.auth() == "password" and "app password" in plain.hint.text()
    plain.method.setCurrentIndex(plain.method.findData("google"))
    plain.method.activated.emit(plain.method.currentIndex())
    assert not plain.add_button.isEnabled() and "client ID" in plain.hint.text()
    _, ready = _oauth_dialog(app, FakeOAuth(), "me@gmail.com")
    assert ready.auth() == "google" and ready.add_button.text() == "Sign in with Google"
    ready.method.setCurrentIndex(ready.method.findData("password"))  # the user can still choose a password
    ready.method.activated.emit(ready.method.currentIndex())
    assert ready.auth() == "password" and ready.form.isRowVisible(ready.password)


def test_a_school_on_google_can_be_chosen_by_hand_and_uses_gmails_server(app):
    from tests.test_accounts import FakeOAuth
    _, dialog = _oauth_dialog(app, FakeOAuth(), "me@school.example.edu")
    assert dialog.auth() == "password" and dialog.draft().host == "imap.school.example.edu"
    dialog.method.setCurrentIndex(dialog.method.findData("google"))
    dialog.method.activated.emit(dialog.method.currentIndex())
    assert dialog.draft().host == "imap.gmail.com" and dialog.add_button.isEnabled()


def test_closing_the_dialog_while_the_browser_is_open_stops_the_wait(app):
    import threading
    from missive.application.errors import SourceError
    from tests.test_accounts import FakeOAuth

    class Waiting(FakeOAuth):
        def __init__(self):
            super().__init__()
            self.waiting = threading.Event()
            self.stop = threading.Event()

        def authorize(self, provider, address):
            self.waiting.set()
            if not self.stop.wait(10):
                raise AssertionError("never cancelled")
            raise SourceError("The sign-in was cancelled.")

        def cancel(self):
            self.stop.set()

    oauth = Waiting()
    service, dialog = _oauth_dialog(app, oauth)
    dialog.add_button.click()
    _settle(app, oauth.waiting.is_set)
    assert dialog.add_button.text() == "Waiting for your browser…" and not dialog.add_button.isEnabled()
    dialog.reject()  # must come back at once instead of hanging for minutes
    assert oauth.stop.is_set() and dialog.added is None and service.accounts() == []


def test_a_refused_sign_in_shows_why_and_adds_nothing(app):
    from missive.application.errors import SourceError
    from tests.test_accounts import FakeOAuth

    class Refusing(FakeOAuth):
        def authorize(self, provider, address):
            raise SourceError("The sign-in was cancelled.")
    service, dialog = _oauth_dialog(app, Refusing())
    dialog.add_button.click()
    _settle(app, lambda: not dialog.error.isHidden())
    assert "cancelled" in dialog.error.text() and service.accounts() == [] and dialog.add_button.isEnabled()


def _service_with(source, accounts=("Home",)):
    from missive.application.services import MailService
    from missive.domain import Account
    from missive.infrastructure.passwords import MemoryPasswords
    from missive.infrastructure.sqlite_store import SqliteStore
    store = SqliteStore(":memory:")
    for name in accounts:
        store.add_account(Account(0, name, f"{name.lower()}@example.org", "imap.example.org"))
    return MailService(store, source, MemoryPasswords())


class SlowSource:
    """A mailbox on a slow connection: what it is asked for waits until the test lets it through."""

    def __init__(self):
        import threading
        from missive.infrastructure.demo_source import DemoSource
        self.inner = DemoSource()
        self.gate = threading.Event()
        self.bodies = []

    def check(self, account, secret):
        pass

    def folders(self, account):
        self.gate.wait(10)
        return self.inner.folders(account)

    def headers(self, account, folder, after_uid):
        return self.inner.headers(account, folder, after_uid)

    def body(self, account, folder, uid, background=False):
        self.bodies.append(uid)
        self.gate.wait(10)
        return self.inner.body(account, folder, uid)


def test_checking_mail_on_a_slow_server_leaves_the_window_usable(app):
    source = SlowSource()
    service = _service_with(source, ("School", "Home"))
    window = MainWindow(service)
    window.show()
    window.sync()  # must return at once, not after the server answers
    assert window._thread is not None and not window.busy.isHidden() and not window.sync_button.isEnabled()
    app.processEvents()
    assert window.status.text()
    source.gate.set()
    _settle(app, lambda: window._thread is None)
    assert window.busy.isHidden() and window.sync_button.isEnabled() and titles(window)
    window.close()


def test_opening_a_letter_that_must_be_fetched_waits_in_the_background_and_ignores_stale_answers(app):
    source = SlowSource()
    source.gate.set()
    service = _service_with(source, ("School", "Home"))
    service.sync()
    window = MainWindow(service)
    window.show()
    source.gate.clear()  # from now on the server is slow
    window.threads.setCurrentRow(row_of(window, "ER diagram homework"))
    assert window.subject.text() == "ER diagram homework" and window._record is None
    assert window.reader.placeholderText() == "Loading…"  # the window answered, the letter is on its way
    window.threads.setCurrentRow(row_of(window, "Dinner on Saturday?"))  # the user moves on
    source.gate.set()
    _settle(app, lambda: window._record is not None)
    _settle(app, lambda: len(window._open_tasks) == 0)
    assert window.subject.text() == "Dinner on Saturday?" and "pizza" in window.reader.toPlainText()
    window.close()


def test_a_letter_you_open_is_marked_read_in_the_list_at_once_even_before_its_text_arrives(window, app):
    before = window.nav[("all", None)].unread
    row = row_of(window, "Dinner on Saturday?")  # unread, a single message
    assert window.threads.item(row).data(THREAD).unread == 1
    window.threads.setCurrentRow(row)
    # no settling: the text may still be on its way, but the row and the counts change this instant
    assert window.threads.item(row).data(THREAD).unread == 0
    assert window.nav[("all", None)].unread == before - 1
    _settle(app, lambda: window._record is not None)
    assert window.threads.item(row).data(THREAD).unread == 0 and window.threads.currentRow() == row


def test_opening_part_of_a_conversation_only_lowers_its_unread_count_by_the_letter_read(window, app):
    row = row_of(window, "ER diagram homework")  # the demo's thread has two unread letters (1 and 3)
    assert window.threads.item(row).data(THREAD).unread == 2
    window.threads.setCurrentRow(row)  # opens the newest
    assert window.threads.item(row).data(THREAD).unread == 1
    _settle(app, lambda: window._record is not None)
    assert "unread" in window.subtitle.text()


def test_reading_a_letter_does_not_move_the_list(window, app):
    bar = window.threads.verticalScrollBar()
    window.resize(900, 300)  # short window: the list scrolls
    app.processEvents()
    bar.setValue(bar.maximum())
    place = bar.value()
    window.threads.setCurrentRow(window.threads.count() - 1)
    _settle(app, lambda: window._record is not None)
    assert bar.value() >= place - 2  # it stayed (an update of one row, not a rebuild from the top)
