from __future__ import annotations

from dataclasses import dataclass

from ..domain import (AUTH_METHODS, OAUTH_HOSTS, Account, Message, clean_html, group, guess_server, link_targets,
                      text_of, valid_address)
from .errors import ApplicationError, NotFound, SourceError
from .ports import MailSource, MessageStore, OAuthClient, PasswordStore
from .records import AccountDraft, AccountRecord, FolderRecord, MessageRecord, ServerGuess, SyncReport, ThreadRecord

PER_FOLDER = 200  # how many of the newest messages a folder shows


class MailService:
    """Use cases for reading mail: fetch what's new, list conversations, open a message."""

    def __init__(self, store: MessageStore, source: MailSource, passwords: PasswordStore | None = None,
                 oauth: OAuthClient | None = None):
        self._store = store
        self._source = source
        self._passwords = passwords
        self._oauth = oauth

    # ---- accounts and folders ----

    def accounts(self) -> list[AccountRecord]:
        return [AccountRecord(a.id, a.name, a.address, a.color) for a in self._store.accounts()]

    def add_account(self, account: Account) -> AccountRecord:
        saved = self._store.add_account(account)
        return AccountRecord(saved.id, saved.name, saved.address, saved.color)

    # ---- account setup ----

    COLORS = ("#5b5bd6", "#30a46c", "#e5484d", "#f5a524", "#0091ff", "#a25bd6")

    def guess_server(self, address: str) -> ServerGuess | None:
        server = guess_server(address)
        return ServerGuess(server.host, server.port, server.app_password, server.oauth) if server else None

    def oauth_host(self, provider: str) -> str:
        """The IMAP server for a Google or Microsoft account, even on the user's own domain."""
        return OAUTH_HOSTS.get(provider, "")

    def oauth_available(self, provider: str) -> bool:
        return self._oauth is not None and self._oauth.available(provider)

    def cancel_authorization(self) -> None:
        """The user closed the sign-in window while the browser was open."""
        if self._oauth is not None:
            self._oauth.cancel()

    def authorize(self, provider: str, address: str) -> str:
        """Let the user approve Missive in their browser; returns the refresh token to keep in the keyring.
        Waits for the user, so run it on a worker thread."""
        if provider not in AUTH_METHODS or provider == "password":
            raise ApplicationError("Choose Google or Microsoft to sign in without a password.")
        if not valid_address(address.strip()):
            raise ApplicationError("That doesn't look like an email address.")
        if self._oauth is None or not self._oauth.available(provider):
            raise ApplicationError("This sign-in isn't set up yet: add its client ID (see docs/OAUTH.md).")
        return self._oauth.authorize(provider, address.strip())

    def _account_from(self, draft: AccountDraft, account_id: int = 0, color: str = "") -> Account:
        address = draft.address.strip()
        if not valid_address(address):
            raise ApplicationError("That doesn't look like an email address.")
        host = draft.host.strip()
        if not host:
            raise ApplicationError("Enter the mail server (for example imap.example.com).")
        if not 0 < draft.port < 65536:
            raise ApplicationError("The port must be a number between 1 and 65535.")
        if draft.auth not in AUTH_METHODS:
            raise ApplicationError("Choose how to sign in: password, Google or Microsoft.")
        if not draft.password and draft.auth == "password":
            raise ApplicationError("Enter the password.")
        if not draft.password:
            raise ApplicationError("Sign in first, in your browser.")
        username = draft.username.strip()
        return Account(account_id, draft.name.strip() or address, address, host, draft.port,
                       "" if username == address else username, color or self.COLORS[0], draft.auth)

    def check_account(self, draft: AccountDraft) -> None:
        """Try the sign-in without saving anything. Network only: safe on a worker thread."""
        self._source.check(self._account_from(draft), draft.password)

    def add_new_account(self, draft: AccountDraft) -> AccountRecord:
        """Save a checked account and its password (in the keyring, never the database)."""
        if self._passwords is None:
            raise ApplicationError("There is nowhere safe to keep the password on this computer.")
        color = self.COLORS[len(self._store.accounts()) % len(self.COLORS)]
        saved = self._store.add_account(self._account_from(draft, 0, color))
        try:
            self._passwords.set(saved.id, draft.password)
        except Exception as e:
            self._store.remove_account(saved.id)  # no password, no account
            raise ApplicationError(f"The password couldn't be saved in the system keyring: {e}") from e
        return AccountRecord(saved.id, saved.name, saved.address, saved.color)

    def remove_account(self, account_id: int) -> None:
        """Forget an account: its stored mail and its password. Nothing changes on the server."""
        self._store.remove_account(account_id)
        if self._passwords is not None:
            try:
                self._passwords.delete(account_id)
            except Exception:
                pass  # already gone

    def folders(self) -> list[FolderRecord]:
        unread, totals = self._store.unread_counts(), self._store.totals()
        order = {"inbox": 0, "drafts": 1, "sent": 2, "archive": 3, "junk": 4, "trash": 5, "": 6}
        folders = sorted(self._store.folders(), key=lambda f: (f.account_id, order.get(f.role, 6), f.name.casefold()))
        return [FolderRecord(f.account_id, f.name, f.role, unread.get(f.key, 0), totals.get(f.key, 0))
                for f in folders]

    # ---- fetching ----

    def sync(self, account_id: int | None = None) -> SyncReport:
        """Fetch folders and the headers of new messages. Bodies come when a message is opened."""
        new = folders = 0
        for account in self._store.accounts():
            if account_id is not None and account.id != account_id:
                continue
            try:
                found = self._source.folders(account)
                self._store.save_folders(found)
                for folder in found:
                    folders += 1
                    after = self._store.max_uid(account.id, folder.name)
                    new += self._store.save_messages(self._source.headers(account, folder.name, after))
            except SourceError:
                raise
            except Exception as e:  # a network or protocol problem, whatever its type
                raise SourceError(f"{account.name}: {e}") from e
        return SyncReport(new, folders)

    # ---- lists ----

    def threads(self, account_id: int | None = None, folder: str | None = None,
                query: str = "") -> list[ThreadRecord]:
        query = query.strip()
        messages = (self._store.search(query, 500) if query
                    else self._store.messages(account_id, folder, PER_FOLDER))
        if query and account_id is not None:
            messages = [m for m in messages if m.account_id == account_id]
        return [_thread_record(t) for t in group(messages)]

    # ---- one message ----

    def open(self, account_id: int, folder: str, uid: int, load_images: bool = False,
             mark_seen: bool = True) -> MessageRecord:
        m = self._store.message(account_id, folder, uid)
        if m is None:
            raise NotFound("That message is gone.")
        if not m.fetched:
            account = next((a for a in self._store.accounts() if a.id == account_id), None)
            if account is None:
                raise NotFound("That account is gone.")
            try:
                text, html = self._source.body(account, folder, uid)
            except Exception as e:
                raise SourceError(f"{account.name}: {e}") from e
            self._store.save_body(account_id, folder, uid, text, html)
            m = self._store.message(account_id, folder, uid)
        if mark_seen and not m.seen:
            self._store.set_seen(account_id, folder, uid, True)
            m.seen = True
        return _message_record(m, load_images)

    def set_seen(self, key: tuple[int, str, int], seen: bool):
        self._store.set_seen(*key, seen)

    def toggle_flag(self, key: tuple[int, str, int]) -> bool:
        m = self._store.message(*key)
        if m is None:
            raise NotFound("That message is gone.")
        self._store.set_flagged(*key, not m.flagged)
        return not m.flagged


def _thread_record(t) -> ThreadRecord:
    last = t.latest
    people = ", ".join(a.display.split(" ")[0] if a.name else a.email.split("@")[0] for a in t.participants[:3])
    return ThreadRecord(t.id, last.account_id, t.subject or "(no subject)", people, last.snippet,
                        last.sent, t.unread, len(t.messages), t.flagged,
                        any(m.has_attachments for m in t.messages),
                        tuple(m.key for m in t.messages))


def _message_record(m: Message, load_images: bool) -> MessageRecord:
    if m.body_html:
        safe, blocked = clean_html(m.body_html, load_images)
        text = m.body_text or text_of(m.body_html)
    else:
        import html as _html
        text = m.body_text or ""
        safe, blocked = "<p>" + _html.escape(text).replace("\n", "<br>") + "</p>", 0
    return MessageRecord(
        m.account_id, m.folder, m.uid, m.subject or "(no subject)", m.sender.display, m.sender.email,
        ", ".join(str(a) for a in m.to), ", ".join(str(a) for a in m.cc), m.sent, m.seen, m.flagged,
        safe, text, blocked, tuple(link_targets(m.body_html or "")))
