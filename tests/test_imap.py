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


# ---- kept connections, partial bodies and the first sync ----

class Counting(FakeImap):
    """A fake that notices how often it is asked to sign in, and can pretend the server hung up."""

    def __init__(self):
        super().__init__()
        self.logins = 0
        self.alive = True

    def login(self, user, password):
        self.logins += 1

    def noop(self):
        if not self.alive:
            raise OSError("connection reset")
        self.calls.append(("noop",))
        return "OK", []


def test_reading_several_letters_signs_in_once_and_asks_only_for_the_start_of_each():
    connections = []

    def connect(account):
        connections.append(Counting())
        return connections[-1]
    src = ImapSource(lambda i: "secret", connect=connect)
    src.body(ACCOUNT, "INBOX", 7)
    src.body(ACCOUNT, "INBOX", 8)
    assert len(connections) == 1 and connections[0].logins == 1  # the second letter reused the connection
    selects = [c for c in connections[0].calls if c[0] == "select"]
    assert selects == [("select", '"INBOX"', True)]  # and didn't open the folder again
    fetches = [c for c in connections[0].calls if c[0] == "uid"]
    assert all("BODY.PEEK[]<0." in c[3] for c in fetches)  # never the whole message with its attachments


def test_reading_and_syncing_use_separate_connections_so_a_long_sync_never_delays_a_letter():
    connections = []

    def connect(account):
        connections.append(Counting())
        return connections[-1]
    src = ImapSource(lambda i: "secret", connect=connect)
    src.folders(ACCOUNT)
    src.body(ACCOUNT, "INBOX", 7)
    assert len(connections) == 2


def test_a_connection_the_server_dropped_is_replaced_quietly():
    connections = []

    def connect(account):
        connections.append(Counting())
        return connections[-1]
    src = ImapSource(lambda i: "secret", connect=connect)
    src.body(ACCOUNT, "INBOX", 7)
    connections[0].alive = False  # the server hung up while the app sat idle
    text, _html = src.body(ACCOUNT, "INBOX", 7)
    assert len(connections) == 2 and text.strip() == "Hello plain"


def test_a_failed_call_throws_the_connection_away():
    connections = []

    class Breaks(Counting):
        def uid(self, command, *args):
            raise OSError("broken pipe")

    def connect(account):
        connections.append(Breaks() if not connections else Counting())
        return connections[-1]
    src = ImapSource(lambda i: "secret", connect=connect)
    with pytest.raises(OSError):
        src.body(ACCOUNT, "INBOX", 7)
    assert src.body(ACCOUNT, "INBOX", 7)[0].strip() == "Hello plain" and len(connections) == 2


class Big(Counting):
    """A folder of 500 messages, UIDs 1 to 500."""

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [b" ".join(str(n).encode() for n in range(1, 501))]
        return super().uid(command, *args)


def test_a_first_sync_asks_only_for_the_newest_messages_of_a_big_folder():
    fake = Big()
    ImapSource(lambda i: "x", connect=lambda a: fake).headers(ACCOUNT, "INBOX", 0)
    fetch = next(c for c in fake.calls if c[0] == "uid" and c[1] == "FETCH")
    assert fetch[2] == "201:*"  # 300 of 500, not all of them


def test_a_small_folder_is_fetched_whole_on_the_first_sync():
    fake = Counting()
    fake.uid = lambda command, *args: ("OK", [b"1 2 3"]) if command == "SEARCH" else FakeImap.uid(fake, command, *args)
    ImapSource(lambda i: "x", connect=lambda a: fake).headers(ACCOUNT, "INBOX", 0)
    fetch = next(c for c in fake.calls if c[0] == "uid" and c[1] == "FETCH")
    assert fetch[2] == "1:*"


def test_close_signs_out_of_every_kept_connection():
    fake = Counting()
    src = ImapSource(lambda i: "x", connect=lambda a: fake)
    src.body(ACCOUNT, "INBOX", 7)
    src.close()
    assert ("logout",) in fake.calls


# ---- fetching ahead, quiet folders, folder names ----

def test_fetching_ahead_has_its_own_connection_so_a_clicked_letter_never_waits_behind_it():
    connections = []

    def connect(account):
        connections.append(Counting())
        return connections[-1]
    src = ImapSource(lambda i: "secret", connect=connect)
    src.body(ACCOUNT, "INBOX", 7, background=True)
    src.body(ACCOUNT, "INBOX", 8)
    assert len(connections) == 2


class Quiet(Counting):
    """A folder whose next UID is 8 (so its newest message is UID 7)."""

    def status(self, folder, what):
        self.calls.append(("status", folder, what))
        return "OK", [b'"INBOX" (UIDNEXT 8)']


def test_a_folder_with_nothing_new_is_skipped_after_one_cheap_status_call():
    fake = Quiet()
    got = ImapSource(lambda i: "x", connect=lambda a: fake).headers(ACCOUNT, "INBOX", after_uid=7)
    assert got == []
    assert not any(c[0] in ("select", "uid") for c in fake.calls)  # never even opened


def test_a_folder_with_something_new_is_still_read():
    fake = Quiet()
    got = ImapSource(lambda i: "x", connect=lambda a: fake).headers(ACCOUNT, "INBOX", after_uid=5)
    assert [m.uid for m in got] == [7]


def test_a_server_without_status_is_simply_read_as_before():
    got = source(FakeImap()).headers(ACCOUNT, "INBOX", after_uid=5)  # FakeImap has no status()
    assert [m.uid for m in got] == [7]


def test_folder_names_are_decoded_for_people():
    from missive.domain import decode_mailbox_name, display_name
    assert display_name("[Gmail]/&BCEEPwQwBDw-") == "Спам"
    assert display_name("[Gmail]/&BBIEQQRP- &BD8EPgRHBEIEMA-") == "Вся почта"
    assert display_name("INBOX") == "INBOX" and display_name("Posta/Inviata") == "Inviata"
    assert decode_mailbox_name("R&AOk-sum&AOk-") == "Résumé" and decode_mailbox_name("A&-B") == "A&B"
    assert decode_mailbox_name("&broken") == "&broken"  # not valid: shown as the server wrote it


def test_the_service_gives_the_screen_decoded_folder_titles(service):
    from missive.domain import Folder
    service._store.save_folders([Folder(1, "[Gmail]/&BCEEPwQwBDw-", "junk")])
    assert "Спам" in [f.title for f in service.folders()]


# ---- pictures that travel inside the message ----

import base64  # noqa: E402

PIXEL = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def related(html: str, parts: dict, padding: int = 0) -> bytes:
    """A multipart/related message: HTML, then pictures by Content-ID, then (maybe) a big attachment."""
    out = (b"From: a@x.org\r\nSubject: s\r\nMIME-Version: 1.0\r\nContent-Type: multipart/related; boundary=R\r\n\r\n"
           b"--R\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html.encode() + b"\r\n")
    for cid, (ctype, data) in parts.items():
        out += (f"--R\r\nContent-Type: {ctype}\r\nContent-ID: <{cid}>\r\nContent-Transfer-Encoding: base64\r\n\r\n"
                ).encode() + base64.encodebytes(data) + b"\r\n"
    if padding:
        out += (b"--R\r\nContent-Type: application/octet-stream\r\nContent-Transfer-Encoding: base64\r\n\r\n"
                + base64.encodebytes(b"x" * padding) + b"\r\n")
    return out + b"--R--\r\n"


def test_pictures_sent_inside_a_message_become_part_of_its_html():
    raw = related('<p>Hi</p><img src="cid:logo@x"><img src=\'cid:Other@x\'><img src="cid:missing@x">',
                  {"logo@x": ("image/png", PIXEL), "Other@x": ("image/gif", b"GIF89a")})
    _text, html, _att = parse_body(raw)
    assert html.count("data:image/png;base64,") == 1 and html.count("data:image/gif;base64,") == 1
    assert "cid:missing@x" in html and "cid:logo" not in html  # what isn't in the message stays unresolved


def test_a_huge_or_unsafe_inline_picture_is_left_out():
    raw = related('<img src="cid:big@x"><img src="cid:svg@x">',
                  {"big@x": ("image/png", b"x" * 2_000_000), "svg@x": ("image/svg+xml", b"<svg onload=alert(1)/>")})
    _text, html, _att = parse_body(raw)
    assert "data:" not in html and "cid:big@x" in html and "cid:svg@x" in html


class Sliced(Counting):
    """A server that honours partial fetches, holding one message."""

    def __init__(self, raw):
        super().__init__()
        self.raw, self.fetches = raw, []

    def uid(self, command, *args):
        self.fetches.append(args)
        item = args[1]
        match = re.search(r"<0\.(\d+)>", item)
        data = self.raw[: int(match.group(1))] if match else self.raw
        return "OK", [(b"1 (UID 7 BODY[] {%d}" % len(data), data), b")"]


import re  # noqa: E402


def test_a_message_whose_pictures_were_cut_off_by_the_partial_fetch_is_fetched_again_in_full():
    from missive.infrastructure.imap_source import BODY_LIMIT
    raw = related('<p>Hello</p><img src="cid:late@x">', {}, padding=0)
    raw = raw.replace(b"--R--\r\n", b"") + b"--R\r\nContent-Type: application/octet-stream\r\nContent-Transfer-Encoding: base64\r\n\r\n" \
        + base64.encodebytes(b"x" * (BODY_LIMIT * 2)) + b"--R\r\nContent-Type: image/png\r\nContent-ID: <late@x>\r\nContent-Transfer-Encoding: base64\r\n\r\n" \
        + base64.encodebytes(PIXEL) + b"--R--\r\n"  # the picture comes after a big attachment: past the first 250 KB
    fake = Sliced(raw)
    _text, html = ImapSource(lambda i: "x", connect=lambda a: fake).body(ACCOUNT, "INBOX", 7)
    assert "data:image/png;base64," in html and len(fake.fetches) == 2
    assert "<0." in fake.fetches[0][1] and "<0." in fake.fetches[1][1]  # both bounded; the second one is bigger


def test_a_message_without_inline_pictures_is_fetched_once():
    fake = Sliced(related("<p>Hello</p>", {}))
    ImapSource(lambda i: "x", connect=lambda a: fake).body(ACCOUNT, "INBOX", 7)
    assert len(fake.fetches) == 1
