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


class FakeOAuth:
    """Stands in for Google / Microsoft: no browser, no network, no real account."""

    def __init__(self, configured=("google", "microsoft")):
        self.configured = configured
        self.asked = []
        self.cancelled = False

    def available(self, provider):
        return provider in self.configured

    def authorize(self, provider, address):
        self.asked.append((provider, address))
        return f"refresh-for-{provider}"

    def cancel(self):
        self.cancelled = True

    def access_token(self, provider, refresh_token):
        return f"access-from-{refresh_token}"


def draft(**kw):
    base = dict(name="Home", address="me@gmail.com", host="imap.gmail.com", port=993, username="me@gmail.com",
                password="app-secret")
    return AccountDraft(**{**base, **kw})


def make(source=None):
    passwords = MemoryPasswords()
    return MailService(SqliteStore(":memory:"), source or DemoSource(), passwords), passwords


def test_known_providers_and_the_imap_dot_guess():
    assert guess_server("a@gmail.com").host == "imap.gmail.com" and guess_server("a@gmail.com").app_password
    assert guess_server("a@outlook.com").oauth == "microsoft" and guess_server("a@gmail.com").oauth == "google"
    assert guess_server("a@outlook.com").host == "outlook.office365.com" and not guess_server("a@libero.it").oauth
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


# ---- signing in with Google or Microsoft ----

def make_oauth(source=None, oauth=None):
    oauth = oauth or FakeOAuth()
    passwords = MemoryPasswords()
    return MailService(SqliteStore(":memory:"), source or DemoSource(), passwords, oauth), passwords, oauth


def test_the_service_says_which_sign_ins_are_set_up_and_which_server_they_use():
    service, _, _ = make_oauth(oauth=FakeOAuth(configured=("google",)))
    assert service.oauth_available("google") and not service.oauth_available("microsoft")
    assert service.oauth_host("google") == "imap.gmail.com" and service.oauth_host("microsoft") == "outlook.office365.com"
    assert not MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords()).oauth_available("google")
    assert service.guess_server("me@outlook.com").oauth == "microsoft"


def test_authorizing_asks_the_provider_for_the_typed_address():
    service, _, oauth = make_oauth()
    assert service.authorize("microsoft", " me@outlook.com ") == "refresh-for-microsoft"
    assert oauth.asked == [("microsoft", "me@outlook.com")]


@pytest.mark.parametrize("provider, address, text", [("password", "me@x.org", "Google or Microsoft"),
                                                     ("google", "nope", "email address")])
def test_authorizing_refuses_nonsense(provider, address, text):
    service, _, oauth = make_oauth()
    with pytest.raises(ApplicationError, match=text):
        service.authorize(provider, address)
    assert oauth.asked == []


def test_authorizing_without_a_client_id_points_at_the_setup_guide():
    service, _, _ = make_oauth(oauth=FakeOAuth(configured=()))
    with pytest.raises(ApplicationError, match="OAUTH.md"):
        service.authorize("google", "me@gmail.com")
    with pytest.raises(ApplicationError, match="OAUTH.md"):
        MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords()).authorize("google", "me@gmail.com")


def test_an_oauth_account_keeps_its_refresh_token_in_the_keyring_and_its_method_in_the_store():
    service, passwords, _ = make_oauth()
    record = service.add_new_account(draft(address="me@outlook.com", host="outlook.office365.com",
                                           password="refresh-for-microsoft", auth="microsoft"))
    stored = service._store.accounts()[0]
    assert stored.auth == "microsoft" and stored.host == "outlook.office365.com"
    assert passwords.get(record.id) == "refresh-for-microsoft"
    assert "refresh-for-microsoft" not in repr(stored)


def test_an_oauth_draft_without_a_token_or_with_an_unknown_method_is_refused():
    service, _, _ = make_oauth()
    with pytest.raises(ApplicationError, match="Sign in first"):
        service.check_account(draft(password="", auth="google"))
    with pytest.raises(ApplicationError, match="Enter the password"):
        service.check_account(draft(password=""))
    with pytest.raises(ApplicationError, match="how to sign in"):
        service.check_account(draft(auth="carrier-pigeon"))


def test_the_oauth_check_goes_through_xoauth2_not_through_a_password_login():
    fake = FakeImap()
    fake.login = lambda user, password: pytest.fail("a password login for an OAuth account")
    used = {}

    def authenticate(mechanism, callback):
        used.update(mechanism=mechanism, first=callback(b""))
    fake.authenticate = authenticate
    oauth = FakeOAuth()
    service, _, _ = make_oauth(ImapSource(lambda i: "x", connect=lambda a: fake, oauth=oauth), oauth)
    service.check_account(draft(address="me@gmail.com", username="me@gmail.com", password="r1", auth="google"))
    assert used == {"mechanism": "XOAUTH2",
                    "first": b"user=me@gmail.com\x01auth=Bearer access-from-r1\x01\x01"}
    assert [c[0] for c in fake.calls] == ["list", "logout"]  # still only looks at the folder list


def test_an_oauth_account_on_a_source_with_no_oauth_says_it_is_not_set_up():
    service, _, _ = make_oauth(ImapSource(lambda i: "x", connect=lambda a: FakeImap()))
    with pytest.raises(SourceError, match="OAUTH.md"):
        service.check_account(draft(password="r1", auth="google"))


def test_cancelling_reaches_the_client():
    service, _, oauth = make_oauth()
    service.cancel_authorization()
    assert oauth.cancelled
    MailService(SqliteStore(":memory:"), DemoSource(), MemoryPasswords()).cancel_authorization()  # nothing to stop
