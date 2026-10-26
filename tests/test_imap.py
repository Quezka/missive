"""The IMAP adapter against a pretend server: it must only ever look, never change anything."""
from datetime import datetime

import pytest

from missive.application.errors import SourceError
from missive.domain import Account
from missive.infrastructure.imap_source import ImapSource, parse_body, parse_headers, role_of

ACCOUNT = Account(1, "School", "me@school.example", "imap.school.example", username="me")

HEADERS = (b"Date: Mon, 26 Oct 2026 09:30:00 +0100\r\nFrom: =?utf-8?q?Prof=2E_Ross=C3=AC?= <rossi@school.example>\r\n"
           b"To: Me <me@school.example>, other@school.example\r\nCc: Giulia <giulia@school.example>\r\n"
           b"Subject: Re: ER diagram\r\nMessage-ID: <b@school>\r\nIn-Reply-To: <a@school>\r\n"
           b"References: <a@school> <b0@school>\r\n\r\n")

FULL = (b"From: Anna <anna@x.org>\r\nTo: me@x.org\r\nSubject: Mixed\r\nMIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=B\r\n\r\n--B\r\nContent-Type: multipart/alternative; boundary=A\r\n\r\n"
        b"--A\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nHello plain\r\n--A\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Hello <b>html</b></p>\r\n--A--\r\n"
        b"--B\r\nContent-Type: application/pdf; name=a.pdf\r\nContent-Disposition: attachment; filename=a.pdf\r\n"
        b"Content-Transfer-Encoding: base64\r\n\r\nJVBERg==\r\n--B--\r\n")


class FakeImap:
    def __init__(self):
        self.calls = []

    def login(self, user, password):
        self.calls.append(("login", user))

    def logout(self):
        self.calls.append(("logout",))

    def list(self):
        self.calls.append(("list",))
        return "OK", [b'(\\HasNoChildren) "/" INBOX', b'(\\HasNoChildren \\Sent) "/" "Sent Items"',
                      b'(\\Noselect \\HasChildren) "/" "[Gmail]"', b'(\\HasNoChildren \\Trash) "/" Trash']

    def select(self, name, readonly=False):
        self.calls.append(("select", name, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append(("uid", command, *args))
        if "HEADER.FIELDS" in args[1]:
            return "OK", [(b"1 (UID 7 FLAGS (\\Seen \\Flagged) BODY[HEADER.FIELDS (DATE FROM)] {10}", HEADERS), b")",
                          (b"2 (UID 3 FLAGS () BODY[HEADER.FIELDS (DATE FROM)] {10}", HEADERS), b")"]
        return "OK", [(b"1 (UID 7 BODY[] {10}", FULL), b")"]


def source(fake):
    return ImapSource(lambda account_id: "secret", connect=lambda account: fake)


def test_folders_get_their_roles_and_unselectable_ones_are_skipped():
    folders = source(FakeImap()).folders(ACCOUNT)
    assert [(f.name, f.role) for f in folders] == [("INBOX", "inbox"), ("Sent Items", "sent"), ("Trash", "trash")]
    assert role_of("", "inbox") == "inbox" and role_of("\\Archive", "Old") == "archive"


def test_headers_are_fetched_read_only_and_only_the_new_ones_are_kept():
    fake = FakeImap()
    got = source(fake).headers(ACCOUNT, "INBOX", after_uid=5)
    assert [m.uid for m in got] == [7]  # "6:*" always returns the newest, even uid 3 here, which is old
    assert ("select", '"INBOX"', True) in fake.calls  # EXAMINE
    fetch = next(c for c in fake.calls if c[0] == "uid")
    assert fetch[1] == "FETCH" and fetch[2] == "6:*" and "BODY.PEEK" in fetch[3]  # never marks anything read
    m = got[0]
    assert m.subject == "Re: ER diagram" and m.sender.name == "Prof. Rossì" and m.sender.email == "rossi@school.example"
    assert m.seen and m.flagged
    assert [a.email for a in m.to] == ["me@school.example", "other@school.example"]
    assert m.message_id == "<b@school>" and m.in_reply_to == "<a@school>" and m.references == ("<a@school>", "<b0@school>")
    assert m.sent == datetime(2026, 10, 26, 9, 30) or m.sent.tzinfo is None  # naive local time


def test_a_body_gives_both_versions_and_notices_attachments():
    text, html, attachments = parse_body(FULL)
    assert text.strip() == "Hello plain" and "<b>html</b>" in html and attachments
    fake = FakeImap()
    t, h = source(fake).body(ACCOUNT, "INBOX", 7)
    assert t.strip() == "Hello plain" and ("select", '"INBOX"', True) in fake.calls
    assert any("BODY.PEEK[]" in str(c) for c in fake.calls)


def test_a_server_that_refuses_us_becomes_a_source_error():
    class Refusing(FakeImap):
        def login(self, user, password):
            import imaplib
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    with pytest.raises(SourceError):
        source(Refusing()).folders(ACCOUNT)


def test_html_only_mail_still_gets_plain_text():
    raw = b"From: a@x.org\r\nSubject: s\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Only <i>html</i></p>"
    text, html, _ = parse_body(raw)
    assert "Only html" in text and "<i>html</i>" in html
    assert parse_headers(1, "INBOX", 1, "", b"Subject: x\r\n\r\n").sender.email == "unknown"
