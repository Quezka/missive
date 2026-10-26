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
    return [window.threads.item(i).data(THREAD).subject for i in range(window.threads.count())]


def test_the_folder_tree_and_the_unified_inbox(window):
    tree = window.folders
    assert tree.topLevelItemCount() == 3  # all inboxes, School, Home
    assert tree.topLevelItem(0).text(0).startswith("All inboxes") and "7" in tree.topLevelItem(0).text(0)
    assert "ER diagram homework" in titles(window) and "Dinner on Saturday?" in titles(window)


def test_picking_a_conversation_shows_the_newest_message_clean_and_marks_it_read(window):
    row = titles(window).index("ER diagram homework")
    window.threads.setCurrentRow(row)
    assert window.subject.text() == "Re: ER diagram homework"
    assert "Both are fine" in window.reader.toPlainText()
    assert window.service.threads(None, "INBOX")[row].unread == 1  # the newest was unread: now read


def test_remote_pictures_stay_out_until_asked_for(window):
    from missive.application.services import MailService  # noqa: F401
    thread = next(t for t in window.service.threads(None, "INBOX") if t.subject == "ER diagram homework")
    window._open(*thread.keys[0])
    assert "not loaded" in window.notice.text() and not window.load_button.isHidden()
    assert "tracker.example" not in window.reader.toHtml()
    window.load_button.click()
    assert window.notice.text() == "" and window.load_button.isHidden()


def test_search_replaces_the_list_and_clearing_it_brings_it_back(window):
    all_titles = titles(window)
    window.search.setText("pizza")
    assert titles(window) == ["Dinner on Saturday?"] and window.title.text() == "Search"
    window.search.clear()
    assert titles(window) == all_titles


def test_flagging_and_syncing_do_not_crash(window):
    window.threads.setCurrentRow(titles(window).index("Dinner on Saturday?"))
    window.star_button.click()
    window.sync_button.click()
    assert window.sync_button.isEnabled() and not window.grab().isNull()


def test_every_folder_can_be_opened(window):
    def walk(item):
        window.folders.setCurrentItem(item)
        for i in range(item.childCount()):
            walk(item.child(i))
    for i in range(window.folders.topLevelItemCount()):
        walk(window.folders.topLevelItem(i))
    assert window.folders.currentItem() is not None


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
    dialog.address.setText("me@outlook.com")
    assert not dialog.add_button.isEnabled() and "OAuth" in dialog.hint.text()
    dialog.address.setText("me@libero.it")
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
