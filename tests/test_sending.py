"""Writing and sending mail. Nothing here touches a real server or sends a real message: SMTP is a fake
object, the demo sender only records, and the screen is driven offscreen."""
import os
import smtplib
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from missive.application.errors import ApplicationError, SourceError
from missive.application.records import DraftRecord
from missive.application.services import MailService
from missive.domain import (
    Account, Address, Outgoing, ValidationError, forward_subject, forwarded, parse_recipients, quote,
    reply_recipients, reply_subject, smtp_for,
)
from missive.infrastructure.demo_source import DemoSender, DemoSource
from missive.infrastructure.passwords import MemoryPasswords
from missive.infrastructure.smtp_sender import SmtpSender, build_message
from missive.infrastructure.sqlite_store import SqliteStore
from tests.test_accounts import FakeOAuth

WHEN = datetime(2026, 10, 27, 9, 30)


# ---- the rules of writing ----

def test_recipients_are_read_from_what_was_typed():
    got = parse_recipients("Anna Rossi <anna@x.org>, b@y.org; c@z.it; d@w.com")
    assert [a.email for a in got] == ["anna@x.org", "b@y.org", "c@z.it", "d@w.com"] and got[0].name == "Anna Rossi"
    assert parse_recipients("") == () and parse_recipients(" , ; ") == ()


@pytest.mark.parametrize("bad", ["nobody", "a@b", "a@x.org, nope", "<>", "a b@x.org"])
def test_a_mistyped_address_is_refused_by_name(bad):
    with pytest.raises(ValidationError, match="doesn't look like an email address"):
        parse_recipients(bad)


def test_a_header_injection_attempt_is_refused():
    with pytest.raises(ValidationError):
        parse_recipients("victim@x.org\r\nBcc: spy@evil.org")


def test_subjects_get_one_prefix_only():
    assert reply_subject("Hello") == "Re: Hello" and reply_subject("Re: Hello") == "Re: Hello"
    assert reply_subject("RE:hi") == "RE:hi" and reply_subject("") == "Re"
    assert forward_subject("Hello") == "Fwd: Hello" and forward_subject("Re: Hello") == "Fwd: Re: Hello"
    assert forward_subject("Fwd: Hello") == "Fwd: Hello"


def test_a_reply_quotes_the_original_line_by_line():
    text = quote("Hi\n\nSee you\nsoon", "Anna", WHEN)
    assert "Anna wrote:" in text and "> Hi\n>\n> See you\n> soon" in text and "27 Oct 2026" in text


def test_reply_all_keeps_the_others_but_never_the_user_or_duplicates():
    sender = Address("s@x.org", "S")
    to = (Address("ME@x.org"), Address("o@x.org"), Address("s@x.org"))
    cc = (Address("c@x.org"), Address("o@x.org"))
    assert reply_recipients(sender, to, cc, "me@x.org", False) == ((sender,), ())
    to_all, cc_all = reply_recipients(sender, to, cc, "me@x.org", True)
    assert [a.email for a in to_all] == ["s@x.org", "o@x.org"] and [a.email for a in cc_all] == ["c@x.org"]


def test_a_forward_carries_the_original_with_a_header():
    text = forwarded("Body text", Address("s@x.org", "S"), WHEN, "Hello", (Address("me@x.org"),))
    assert "Forwarded message" in text and "From: S <s@x.org>" in text and "Subject: Hello" in text
    assert text.rstrip().endswith("Body text")


def test_where_mail_is_sent_from_follows_the_provider():
    assert smtp_for("imap.gmail.com") == ("smtp.gmail.com", 465)
    assert smtp_for("imap.gmail.com", "google", "x@school.edu") == ("smtp.gmail.com", 465)
    assert smtp_for("outlook.office365.com", "microsoft", "me@outlook.com") == ("smtp-mail.outlook.com", 587)
    assert smtp_for("outlook.office365.com", "microsoft", "me@school.edu") == ("smtp.office365.com", 587)
    assert smtp_for("imap.example.org") == ("smtp.example.org", 587) and smtp_for("mail.example.org") == ("smtp.mail.example.org", 587)


# ---- SMTP, against a fake server ----

ACCOUNT = Account(1, "Home", "me@example.org", "imap.example.org", username="me", smtp_host="smtp.example.org",
                  smtp_port=587)
MAIL = Outgoing(Address("me@example.org"), (Address("a@x.org", "Anna"),), "Hello ✓", "Body é",
                (Address("c@x.org"),), (Address("secret@x.org"),), "<orig@x>", ("<first@x>", "<orig@x>"))


class FakeSmtp:
    def __init__(self, fail=None):
        self.calls, self.sent, self.fail = [], [], fail

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if self.fail == "login":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    def auth(self, mechanism, authobject, initial_response_ok=True):
        self.calls.append(("auth", mechanism, authobject(), initial_response_ok))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        if self.fail == "recipients":
            raise smtplib.SMTPRecipientsRefused({"a@x.org": (550, b"no such user")})
        if self.fail == "network":
            raise OSError("Network is unreachable")
        self.sent.append((msg, from_addr, to_addrs))

    def quit(self):
        self.calls.append(("quit",))


def sender(fake, oauth=None):
    asked = []

    def connect(host, port):
        asked.append((host, port))
        return fake
    s = SmtpSender(oauth, connect=connect)
    s.asked = asked
    return s


def test_a_message_is_built_with_bcc_only_in_the_envelope():
    msg = build_message(ACCOUNT, MAIL)
    assert msg["To"] == "Anna <a@x.org>" and msg["Cc"] == "c@x.org" and msg["Bcc"] is None
    assert msg["From"] == "me@example.org" and msg["In-Reply-To"] == "<orig@x>"
    assert msg["References"] == "<first@x> <orig@x>" and msg["Message-ID"].endswith("@example.org>")
    assert msg["Subject"] == "Hello ✓" and "Body é" in msg.get_content() and "secret@x.org" not in msg.as_string()


def test_sending_signs_in_with_the_password_and_delivers_to_everyone_including_bcc():
    fake = FakeSmtp()
    s = sender(fake)
    raw = s.send(ACCOUNT, "app-secret", MAIL)
    assert s.asked == [("smtp.example.org", 587)]
    assert fake.calls[0] == ("login", "me", "app-secret") and fake.calls[-1] == ("quit",)
    _msg, from_addr, to_addrs = fake.sent[0]
    assert from_addr == "me@example.org" and to_addrs == ["a@x.org", "c@x.org", "secret@x.org"]
    assert b"Subject:" in raw and b"secret@x.org" not in raw  # the copy kept for Sent has no Bcc either


def test_an_account_without_its_own_smtp_settings_uses_the_providers():
    google = Account(2, "G", "me@gmail.com", "imap.gmail.com", auth="google")
    fake = FakeSmtp()
    s = sender(fake, FakeOAuth())
    s.send(google, "r1", MAIL)
    assert s.asked == [("smtp.gmail.com", 465)]


def test_a_google_or_microsoft_account_signs_in_with_xoauth2_not_a_password():
    google = Account(2, "G", "me@gmail.com", "imap.gmail.com", auth="google")
    fake = FakeSmtp()
    sender(fake, FakeOAuth()).send(google, "r1", MAIL)
    kind, mechanism, first, initial = fake.calls[0]
    assert (kind, mechanism, initial) == ("auth", "XOAUTH2", True)
    assert first == "user=me@gmail.com\x01auth=Bearer access-from-r1\x01\x01"
    assert not any(c[0] == "login" for c in fake.calls)


def test_oauth_without_a_client_id_says_so():
    google = Account(2, "G", "me@gmail.com", "imap.gmail.com", auth="google")
    with pytest.raises(SourceError, match="OAUTH.md"):
        sender(FakeSmtp(), None).send(google, "r1", MAIL)


@pytest.mark.parametrize("fail, text", [("login", "refused the sign-in"), ("recipients", "refused these recipients"),
                                        ("network", "unreachable")])
def test_a_server_that_says_no_becomes_a_clear_error(fail, text):
    with pytest.raises(SourceError, match=text) as caught:
        sender(FakeSmtp(fail)).send(ACCOUNT, "x", MAIL)
    assert "Home" in str(caught.value) and "couldn't send" in str(caught.value)


def test_the_real_connection_encrypts_before_anything_is_sent(monkeypatch):
    made = []

    class Plain:
        def __init__(self, host, port, timeout=None):
            made.append(("SMTP", host, port, timeout))
            self.calls = []

        def ehlo(self):
            self.calls.append("ehlo")

        def starttls(self, context=None):
            self.calls.append("starttls")
            assert context is not None

    class Tls:
        def __init__(self, host, port, timeout=None, context=None):
            made.append(("SMTP_SSL", host, port, timeout))
            assert context is not None
    monkeypatch.setattr(smtplib, "SMTP", Plain)
    monkeypatch.setattr(smtplib, "SMTP_SSL", Tls)
    starttls = SmtpSender._real_connect("smtp.example.org", 587)
    SmtpSender._real_connect("smtp.example.org", 465)
    assert made == [("SMTP", "smtp.example.org", 587, 30), ("SMTP_SSL", "smtp.example.org", 465, 30)]
    assert starttls.calls == ["ehlo", "starttls", "ehlo"]  # upgraded to TLS before any sign-in


# ---- the service ----

class Source(DemoSource):
    def __init__(self):
        super().__init__(datetime(2026, 10, 26, 12, 0))
        self.copies = []

    def save_sent(self, account, folder, raw):
        self.copies.append((account.id, folder, raw))


def make(auth="password", sender_obj=None, source=None):
    source = source or Source()
    store = SqliteStore(":memory:")
    store.add_account(Account(0, "School", "student@school.example", "imap.school.example", auth=auth))
    passwords = MemoryPasswords()
    service = MailService(store, source, passwords, FakeOAuth(), sender_obj if sender_obj is not None else DemoSender())
    passwords.set(store.accounts()[0].id, "secret")
    service.sync()
    return service, source


def first_key(service, subject="ER diagram homework"):
    thread = next(t for t in service.threads(None, "INBOX") if t.subject == subject)
    return thread.keys[-1]


def test_a_reply_goes_to_the_sender_with_the_original_quoted_and_threaded():
    service, _ = make()
    key = first_key(service)
    service.open(*key)
    draft = service.reply_draft(key)
    assert draft.subject == "Re: ER diagram homework" and "rossi@school.example" in draft.to
    assert "> Both are fine" in draft.text and draft.in_reply_to == "<hw3@school>"
    assert draft.references[-1] == "<hw3@school>" and "<hw1@school>" in draft.references


def test_reply_all_and_forward_start_from_the_right_place():
    service, _ = make()
    key = first_key(service)
    service.open(*key)
    assert service.forward_draft(key).subject == "Fwd: Re: ER diagram homework" and service.forward_draft(key).to == ""
    assert "Forwarded message" in service.forward_draft(key).text
    assert service.reply_draft(key, everyone=True).to.count("@") >= 1


def test_a_new_draft_starts_empty_on_the_chosen_account_and_needs_an_account():
    service, _ = make()
    assert service.new_draft().account_id == service.accounts()[0].id and service.new_draft().to == ""
    empty = MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords(), None, DemoSender())
    with pytest.raises(ApplicationError, match="Add a mail account"):
        empty.new_draft()


def test_sending_checks_everything_first_and_sends_nothing_when_something_is_wrong():
    sender_obj = DemoSender()
    service, _ = make(sender_obj=sender_obj)
    base = DraftRecord(service.accounts()[0].id, "a@x.org", subject="Hi", text="Text")
    for bad, text in ((DraftRecord(base.account_id, "", subject="Hi"), "at least one recipient"),
                      (DraftRecord(base.account_id, "nope", subject="Hi"), "doesn't look like"),
                      (DraftRecord(base.account_id, "a@x.org", cc="also nope"), "doesn't look like"),
                      (DraftRecord(999, "a@x.org"), "account is gone")):
        with pytest.raises(ApplicationError, match=text):
            service.send(bad)
    with pytest.raises(ApplicationError, match="at least one recipient"):
        service.check_draft(DraftRecord(base.account_id))
    assert sender_obj.sent == []
    service.send(base)
    assert len(sender_obj.sent) == 1


def test_the_message_goes_out_from_the_accounts_own_address_with_its_recipients():
    sender_obj = DemoSender()
    service, _ = make(sender_obj=sender_obj)
    service.send(DraftRecord(service.accounts()[0].id, "Anna <a@x.org>", "c@x.org", "b@x.org", " Hi ", "Text",
                             "<o@x>", ("<o@x>",)))
    mail = sender_obj.sent[0]
    assert mail.sender.email == "student@school.example" and mail.subject == "Hi"
    assert [a.email for a in mail.to] == ["a@x.org"] and [a.email for a in mail.bcc] == ["b@x.org"]
    assert mail.in_reply_to == "<o@x>"


def test_a_password_account_keeps_a_copy_in_sent_but_google_does_not_need_one():
    service, source = make("password")
    service.send(DraftRecord(service.accounts()[0].id, "a@x.org", subject="Hi"))
    assert len(source.copies) == 1 and source.copies[0][1] == "Sent"
    service, source = make("google")
    service.send(DraftRecord(service.accounts()[0].id, "a@x.org", subject="Hi"))
    assert source.copies == []  # Gmail files sent mail by itself


def test_a_failed_copy_in_sent_does_not_undo_a_sent_message():
    service, source = make("password")
    source.save_sent = lambda *a: (_ for _ in ()).throw(OSError("no room"))
    service.send(DraftRecord(service.accounts()[0].id, "a@x.org", subject="Hi"))  # no exception


def test_without_a_sender_nothing_can_be_sent():
    service = MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords())
    assert not service.can_send()
    with pytest.raises(ApplicationError, match="isn't available"):
        service.send(DraftRecord(1, "a@x.org"))


def test_a_server_that_refuses_is_reported_and_nothing_is_saved_in_sent():
    class Refusing:
        def send(self, account, secret, mail):
            raise SourceError("School: couldn't send (nope)")
    service, source = make(sender_obj=Refusing())
    with pytest.raises(SourceError, match="couldn't send"):
        service.send(DraftRecord(service.accounts()[0].id, "a@x.org", subject="Hi"))
    assert source.copies == []


def test_the_demo_sender_only_records():
    demo = DemoSender()
    assert demo.send(ACCOUNT, "x", MAIL) == b"" and demo.sent == [MAIL]


# ---- on screen ----

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from missive.presentation.compose_dialog import ComposeDialog  # noqa: E402
from missive.presentation.main_window import THREAD, MainWindow  # noqa: E402
from missive.presentation.qt_app import create_application  # noqa: E402
from tests.test_ui import _settle, row_of  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return create_application(["test"])


def window_with(sender_obj, app):
    service, source = make(sender_obj=sender_obj)
    w = MainWindow(service)
    w.show()
    w.SEND_DELAY = 5
    return w, service


def open_first(w, app, subject="ER diagram homework"):
    w.threads.setCurrentRow(row_of(w, subject))
    _settle(app, lambda: w._record is not None)


def test_the_reader_offers_reply_reply_all_and_forward_once_a_letter_is_open(app):
    w, _ = window_with(DemoSender(), app)
    assert not w.reply_button.isEnabled() and not w.forward_button.isEnabled()  # nothing open yet
    open_first(w, app)
    assert w.reply_button.isEnabled() and w.reply_all_button.isEnabled() and w.forward_button.isEnabled()
    w.reply_button.click()
    composer = w._composers[-1]
    assert composer.subject.text() == "Re: ER diagram homework" and "rossi@school.example" in composer.to.text()
    assert composer.body.toPlainText().lstrip().startswith("On ") and "> Both are fine" in composer.body.toPlainText()
    assert composer.body.textCursor().position() == 0  # typing starts above the quote
    composer._initial = composer.draft()  # (nothing typed: closing must not ask)
    composer.close()
    w.close()


def test_a_new_message_starts_empty_on_the_current_account(app):
    w, _ = window_with(DemoSender(), app)
    w.compose_button.click()
    composer = w._composers[-1]
    assert composer.to.text() == "" and composer.subject.text() == "" and composer.sender.count() == 1
    assert composer.windowTitle() == "New message"
    composer.close()
    w.close()


def test_the_compose_window_explains_a_mistake_and_does_not_send(app):
    w, _ = window_with(DemoSender(), app)
    w.compose_button.click()
    composer = w._composers[-1]
    composer.to.setText("not an address")
    composer.send_button.click()
    assert not composer.error.isHidden() and "doesn't look like" in composer.error.text() and w._pending is None
    composer.to.setText("")
    composer.send_button.click()
    assert "at least one recipient" in composer.error.text()
    composer.discard_button.click()  # changed? yes: it asks; the test says yes
    w.close()


def test_pressing_send_waits_so_it_can_be_undone_and_undo_brings_the_message_back(app):
    sender_obj = DemoSender()
    w, _ = window_with(sender_obj, app)
    w.compose_button.click()
    composer = w._composers[-1]
    composer.to.setText("a@x.org")
    composer.subject.setText("Hi")
    composer.body.setPlainText("Text")
    composer.send_button.click()
    assert w._pending is not None and not w.undo_bar.isHidden() and "a@x.org" in w.undo_text.text()
    assert sender_obj.sent == []  # still waiting
    w.undo_button.click()
    assert w._pending is None and w.undo_bar.isHidden() and sender_obj.sent == []
    back = w._composers[-1]
    assert back.to.text() == "a@x.org" and back.subject.text() == "Hi" and back.body.toPlainText() == "Text"
    back._sending = True
    back.close()
    w.close()


def test_a_message_goes_out_when_the_wait_is_over_and_the_window_says_so(app):
    sender_obj = DemoSender()
    w, _ = window_with(sender_obj, app)
    w.SEND_DELAY = 0
    w.compose_button.click()
    composer = w._composers[-1]
    composer.to.setText("a@x.org")
    composer.subject.setText("Hi")
    composer.body.setPlainText("Text")
    composer.send_button.click()
    _settle(app, lambda: len(sender_obj.sent) == 1 and not w._send_tasks)
    assert sender_obj.sent[0].subject == "Hi" and w.status.text() == "Message sent" and w.undo_bar.isHidden()
    w.close()


def test_closing_the_window_while_a_send_waits_still_sends_it(app):
    sender_obj = DemoSender()
    w, _ = window_with(sender_obj, app)
    w.compose_button.click()
    composer = w._composers[-1]
    composer.to.setText("a@x.org")
    composer.subject.setText("Hi")
    composer.send_button.click()
    assert w._pending is not None
    w.close()
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(5000)
    assert len(sender_obj.sent) == 1  # Send was pressed: closing doesn't take it back


def test_when_the_server_refuses_the_message_comes_back_to_be_fixed_and_nothing_is_lost(app, monkeypatch):
    class Refusing(DemoSender):
        def send(self, account, secret, mail):
            raise SourceError("School: couldn't send (the server said no)")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    w, _ = window_with(Refusing(), app)
    w.SEND_DELAY = 0
    w.compose_button.click()
    composer = w._composers[-1]
    composer.to.setText("a@x.org")
    composer.subject.setText("Important")
    composer.body.setPlainText("Do not lose me")
    composer.send_button.click()
    _settle(app, lambda: shown)
    assert "the server said no" in shown[0] and w.status.text() == "Couldn't send the message"
    back = w._composers[-1]
    assert back.subject.text() == "Important" and back.body.toPlainText() == "Do not lose me"
    back._sending = True
    back.close()
    w.close()


def test_discarding_a_message_you_changed_asks_first(app, monkeypatch):
    w, _ = window_with(DemoSender(), app)
    w.compose_button.click()
    composer = w._composers[-1]
    composer.body.setPlainText("half a thought")
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.No)
    composer.discard_button.click()
    assert asked == ["Discard this message?"] and composer.isVisible()  # said no: it stays
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    composer.discard_button.click()
    assert not composer.isVisible()
    w.close()
