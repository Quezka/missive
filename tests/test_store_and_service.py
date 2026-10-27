from datetime import datetime

NOW = datetime(2026, 10, 26, 12, 0)

from missive.application.errors import NotFound
from missive.domain import Account, Address, Message
from missive.infrastructure.sqlite_store import SqliteStore

import pytest


def test_demo_sync_fetches_headers_and_counts_unread(service):
    folders = {(f.account_id, f.name): f for f in service.folders()}
    assert {f.name for f in folders.values()} == {"INBOX", "Sent", "Archive"}
    assert sum(f.unread for f in folders.values() if f.role == "inbox") == 7
    assert service.sync().new == 0  # nothing new the second time
    inbox_threads = service.threads(None, "INBOX")
    subjects = [t.subject for t in inbox_threads]
    assert "ER diagram homework" in subjects and subjects[0] == "Weekly newsletter"  # newest first
    homework = next(t for t in inbox_threads if t.subject == "ER diagram homework")
    assert homework.count == 3 and homework.unread == 2  # the replies joined the conversation


def test_opening_fetches_the_body_once_marks_it_read_and_cleans_the_html(service):
    thread = next(t for t in service.threads(None, "INBOX") if t.subject == "ER diagram homework")
    first = thread.keys[0]
    record = service.open(*first)
    assert "<script" not in record.html and "tracker.example" not in record.html
    assert record.blocked_images == 1 and record.links == ("https://school.example/notes",)
    assert service.open(*first, load_images=True).blocked_images == 0  # asked for: they are loaded
    again = service.threads(None, "INBOX")
    homework = next(t for t in again if t.subject == "ER diagram homework")
    assert homework.unread == 1  # the opened one is read now
    with pytest.raises(NotFound):
        service.open(1, "INBOX", 999)


def test_flagging_and_reading_state_persist(service):
    key = next(t for t in service.threads(None, "INBOX") if t.subject == "Dinner on Saturday?").keys[0]
    assert service.toggle_flag(key) is False  # it was flagged in the demo: now off
    assert service.toggle_flag(key) is True
    service.set_seen(key, False)
    assert next(t for t in service.threads(None, "INBOX") if t.subject == "Dinner on Saturday?").unread == 1


def test_search_finds_words_in_subjects_senders_snippets_and_fetched_bodies(service):
    assert [t.subject for t in service.threads(query="pizza")] == ["Dinner on Saturday?"]  # in the snippet
    assert [t.subject for t in service.threads(query="ROSSI")]  # the sender, case-insensitive
    assert [t.subject for t in service.threads(query="homewo")]  # a prefix of a word
    assert service.threads(query="zzzz-nothing") == []
    assert service.threads(query="course page") == []  # only in the HTML body, which isn't fetched yet
    hw = next(t for t in service.threads(None, "INBOX") if t.subject == "ER diagram homework")
    service.open(*hw.keys[0])
    assert [t.subject for t in service.threads(query="course page")] == ["ER diagram homework"]


def test_a_message_is_stored_once_even_if_the_server_lists_it_again():
    store = SqliteStore(":memory:")
    acct = store.add_account(Account(0, "A", "a@x.org", "h"))
    m = Message(acct.id, "INBOX", 1, "Hi", Address("b@x.org"), datetime(2026, 1, 1))
    assert store.save_messages([m]) == 1 and store.save_messages([m]) == 0
    assert store.max_uid(acct.id, "INBOX") == 1


def test_a_database_from_before_oauth_gains_the_auth_column_and_keeps_its_accounts(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL, host TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 993, username TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT '#5b5bd6');
        INSERT INTO accounts (name, address, host) VALUES ('Old', 'me@libero.it', 'imapmail.libero.it');
    """)
    old.commit()
    old.close()
    from missive.infrastructure.sqlite_store import SqliteStore
    store = SqliteStore(path)
    assert [(a.address, a.auth) for a in store.accounts()] == [("me@libero.it", "password")]
    from missive.domain import Account
    saved = store.add_account(Account(0, "G", "me@gmail.com", "imap.gmail.com", auth="google"))
    assert [a.auth for a in store.accounts()] == ["password", "google"] and saved.auth == "google"
    store.close()
    assert [a.auth for a in SqliteStore(path).accounts()] == ["password", "google"]  # reopening is harmless


# ---- background work: prefetching, partial failures, stopping, threads ----

def test_prefetch_downloads_the_text_of_the_newest_inbox_mail_once(service):
    fresh = sorted(service._store.messages(None, "INBOX", 50), key=lambda m: m.uid)
    assert fresh and not any(m.fetched for m in fresh)  # a listing carries no bodies
    first = service.prefetch()
    assert first == 8  # the demo's eight inbox messages
    assert not service.needs_fetch(fresh[0].account_id, "INBOX", fresh[0].uid)
    assert service.prefetch() == 0  # nothing left to fetch


def test_prefetch_can_be_stopped_and_gives_up_on_an_account_whose_server_fails(service):
    assert service.prefetch(stop=lambda: True) == 0
    from missive.application.services import MailService

    class Failing:
        def body(self, *a):
            raise OSError("down")
    broken = MailService(service._store, Failing(), None)
    assert broken.prefetch() == 0  # no crash: the letters will be fetched when opened


class PartlyBroken:
    """A server where one folder can't be read."""

    def __init__(self, inner, bad="Sent"):
        self.inner, self.bad = inner, bad

    def folders(self, account):
        return self.inner.folders(account)

    def headers(self, account, folder, after_uid):
        if folder == self.bad:
            raise OSError("folder is corrupt")
        return self.inner.headers(account, folder, after_uid)


def test_one_unreadable_folder_is_reported_and_the_rest_still_arrives():
    from missive.application.services import MailService
    from missive.domain import Account
    from missive.infrastructure.demo_source import DemoSource
    from missive.infrastructure.sqlite_store import SqliteStore
    store = SqliteStore(":memory:")
    store.add_account(Account(0, "School", "s@school.example", "imap.school.example"))
    report = MailService(store, PartlyBroken(DemoSource(NOW))).sync()
    assert report.new == 6 - 1 and len(report.problems) == 1 and "Sent" in report.problems[0]
    assert "corrupt" in report.problems[0]


def test_when_nothing_at_all_can_be_read_the_first_problem_becomes_an_error():
    from missive.application.errors import SourceError
    from missive.application.services import MailService
    from missive.domain import Account
    from missive.infrastructure.sqlite_store import SqliteStore

    class Down:
        def folders(self, account):
            raise SourceError("School: the server isn't there")
    store = SqliteStore(":memory:")
    store.add_account(Account(0, "School", "s@school.example", "imap.school.example"))
    with pytest.raises(SourceError, match="isn't there"):
        MailService(store, Down()).sync()


def test_a_sync_reports_progress_and_stops_when_asked(service):
    seen = []

    def progress(account, folder, new):
        seen.append((account, folder))
        return len(seen) < 2  # stop at the second folder
    report = service.sync(progress=progress)
    assert len(seen) == 2 and report.folders <= 1


def test_the_store_can_be_read_while_another_thread_writes_into_it():
    import threading
    from missive.domain import Account, Address, Message
    from missive.infrastructure.sqlite_store import SqliteStore
    store = SqliteStore(":memory:")
    account = store.add_account(Account(0, "A", "a@x.org", "imap.x.org"))
    errors = []

    def write():
        try:
            for uid in range(1, 301):
                store.save_messages([Message(account.id, "INBOX", uid, f"s{uid}", Address("b@x.org"), NOW)])
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    writer = threading.Thread(target=write)
    writer.start()
    while writer.is_alive():
        store.messages(account.id, "INBOX", 50)
        store.unread_counts()
    writer.join()
    assert not errors and store.max_uid(account.id, "INBOX") == 300
