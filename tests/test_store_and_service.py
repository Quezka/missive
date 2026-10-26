from datetime import datetime

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
