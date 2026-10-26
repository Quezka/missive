"""Setting up an account: server guesses, the sign-in check, saving the password safely, removing it all."""
import imaplib
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from missive.application.errors import ApplicationError, SourceError
from missive.application.records import AccountDraft
from missive.application.services import MailService
from missive.domain import guess_server, valid_address
from missive.infrastructure.demo_source import DemoSource
from missive.infrastructure.imap_source import ImapSource
from missive.infrastructure.passwords import MemoryPasswords
from missive.infrastructure.sqlite_store import SqliteStore
from tests.test_imap import FakeImap


def draft(**kw):
    base = dict(name="Home", address="me@gmail.com", host="imap.gmail.com", port=993, username="me@gmail.com",
                password="app-secret")
    return AccountDraft(**{**base, **kw})


def make(source=None):
    passwords = MemoryPasswords()
    return MailService(SqliteStore(":memory:"), source or DemoSource(), passwords), passwords


def test_known_providers_and_the_imap_dot_guess():
    assert guess_server("a@gmail.com").host == "imap.gmail.com" and guess_server("a@gmail.com").app_password
    assert guess_server("a@outlook.com").unsupported == "oauth"
    assert guess_server("a@libero.it").host == "imapmail.libero.it"
    assert guess_server("a@school.example.edu").host == "imap.school.example.edu"
    assert guess_server("not an address") is None and not valid_address("a@b") and valid_address("a@b.co")


def test_adding_saves_the_account_and_puts_the_password_in_the_keyring_not_the_store():
    service, passwords = make()
    record = service.add_new_account(draft())
    assert [a.address for a in service.accounts()] == ["me@gmail.com"]
    assert passwords.get(record.id) == "app-secret"
    stored = service._store.accounts()[0]
    assert "app-secret" not in repr(stored)
    assert stored.username == ""  # the same as the address: nothing to remember


def test_each_account_gets_its_own_colour():
    service, _ = make()
    first = service.add_new_account(draft())
    second = service.add_new_account(draft(address="b@libero.it", name="B"))
    assert first.color != second.color


@pytest.mark.parametrize("bad, text", [({"address": "nope"}, "email address"), ({"host": " "}, "mail server"),
                                       ({"port": 0}, "port"), ({"password": ""}, "password")])
def test_bad_input_is_explained(bad, text):
    service, _ = make()
    with pytest.raises(ApplicationError, match=text):
        service.check_account(draft(**bad))


def test_a_failed_keyring_leaves_no_account_behind():
    class Broken(MemoryPasswords):
        def set(self, account_id, password):
            raise RuntimeError("keyring locked")
    service = MailService(SqliteStore(":memory:"), DemoSource(), Broken())
    with pytest.raises(ApplicationError, match="keyring"):
        service.add_new_account(draft())
    assert service.accounts() == []


def test_removing_forgets_messages_and_password_but_leaves_other_accounts():
    service, passwords = make()
    a = service.add_new_account(draft())
    b = service.add_new_account(draft(address="b@libero.it", name="B"))
    service.sync()
    assert service.threads(a.id, "INBOX") and service.threads(b.id, "INBOX")
    service.remove_account(a.id)
    assert [x.id for x in service.accounts()] == [b.id]
    assert service.threads(a.id, "INBOX") == [] and service.threads(b.id, "INBOX")
    assert service.threads(None, None, "diagram") == [] or all(t.account_id == b.id
                                                              for t in service.threads(None, None, "diagram"))
    with pytest.raises(KeyError):
        passwords.get(a.id)


def test_the_imap_check_signs_in_with_the_typed_password_and_only_lists_folders():
    fake = FakeImap()
    seen = {}
    fake.login = lambda user, password: seen.update(user=user, password=password)
    source = ImapSource(lambda account_id: (_ for _ in ()).throw(AssertionError("keyring not asked")),
                        connect=lambda account: fake)
    service, _ = make(source)
    service.check_account(draft(username="me"))
    assert seen == {"user": "me", "password": "app-secret"}
    assert [c[0] for c in fake.calls] == ["list", "logout"]  # nothing selected, fetched or changed


def test_a_refused_sign_in_says_why():
    class Refuses(FakeImap):
        def login(self, user, password):
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials")
    service, _ = make(ImapSource(lambda i: "x", connect=lambda a: Refuses()))
    with pytest.raises(SourceError, match="AUTHENTICATIONFAILED"):
        service.check_account(draft())


def test_a_server_that_cannot_be_reached_says_so():
    def connect(account):
        raise OSError("Name or service not known")
    service, _ = make(ImapSource(lambda i: "x", connect=connect))
    with pytest.raises(SourceError, match="Name or service"):
        service.check_account(draft())
