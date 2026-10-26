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
