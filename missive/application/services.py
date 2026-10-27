from __future__ import annotations

from dataclasses import dataclass

from ..domain import (AUTH_METHODS, OAUTH_HOSTS, Account, Address, DomainError, Message, Outgoing, check_outgoing,
                      clean_html, display_name, forward_subject, forwarded, group, guess_server, link_targets,
                      parse_recipients, quote, reply_recipients, reply_subject, smtp_for, text_of, valid_address)
from .errors import ApplicationError, NotFound, SourceError
from .ports import MailSender, MailSource, MessageStore, OAuthClient, PasswordStore
from .records import (AccountDraft, AccountRecord, DraftRecord, FolderRecord, MessageRecord, ServerGuess, SyncReport,
                      ThreadRecord)

PER_FOLDER = 200  # how many of the newest messages a folder shows


class MailService:
    """Use cases for reading mail: fetch what's new, list conversations, open a message."""

    def __init__(self, store: MessageStore, source: MailSource, passwords: PasswordStore | None = None,
                 oauth: OAuthClient | None = None, sender: MailSender | None = None):
        self._store = store
        self._source = source
        self._passwords = passwords
        self._oauth = oauth
        self._sender = sender

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
        if server is None:
            return None
        smtp_host, smtp_port = smtp_for(server.host, "password", address)
        return ServerGuess(server.host, server.port, server.app_password, server.oauth, smtp_host, smtp_port)

    def smtp_server(self, address: str, auth: str) -> tuple[str, int]:
        """Where mail is sent from for this address and way of signing in."""
        server = guess_server(address)
        return smtp_for(server.host if server else "", auth, address)

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
                       "" if username == address else username, color or self.COLORS[0], draft.auth,
                       draft.smtp_host.strip(), draft.smtp_port if 0 < draft.smtp_port < 65536 else 587)

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
        return [FolderRecord(f.account_id, f.name, f.role, unread.get(f.key, 0), totals.get(f.key, 0), display_name(f.name))
                for f in folders]

    # ---- fetching ----

    def sync(self, account_id: int | None = None, progress=None) -> SyncReport:
        """Fetch folders and the headers of new messages. Bodies come when a message is opened.

        `progress(account name, folder, new so far)` is called before each folder; when it returns False the
        sync stops there (the user closed the window). A folder that can't be read is skipped and reported;
        an account that can't sign in is skipped too, and only when nothing at all could be read does
        the first problem become an error."""
        new = folders = 0
        problems: list[str] = []
        first: SourceError | None = None
        for account in self._store.accounts():
            if account_id is not None and account.id != account_id:
                continue
            try:
                found = self._source.folders(account)
            except Exception as e:  # a network or protocol problem, whatever its type
                first = first or (e if isinstance(e, SourceError) else SourceError(f"{account.name}: {e}"))
                problems.append(str(first))
                continue
            self._store.save_folders(found)
            for folder in found:
                if progress is not None and progress(account.name, display_name(folder.name), new) is False:
                    return SyncReport(new, folders, tuple(problems))
                try:
                    after = self._store.max_uid(account.id, folder.name)
                    new += self._store.save_messages(self._source.headers(account, folder.name, after))
                    folders += 1
                except Exception as e:
                    problems.append(f"{account.name} / {folder.name}: {e}")
        if problems and folders == 0 and new == 0:
            raise first or SourceError(problems[0])
        return SyncReport(new, folders, tuple(problems))

    # ---- writing ----

    def can_send(self) -> bool:
        return self._sender is not None

    def new_draft(self, account_id: int | None = None) -> DraftRecord:
        accounts = self._store.accounts()
        if not accounts:
            raise ApplicationError("Add a mail account first.")
        return DraftRecord(account_id if account_id in {a.id for a in accounts} else accounts[0].id)

    def _original(self, key: tuple[int, str, int]) -> tuple[Message, Account]:
        m = self._store.message(*key)
        account = next((a for a in self._store.accounts() if a.id == key[0]), None)
        if m is None or account is None:
            raise NotFound("That message is gone.")
        return m, account

    @staticmethod
    def _plain(m: Message) -> str:
        return m.body_text if m.body_text is not None else text_of(m.body_html or "")

    def reply_draft(self, key: tuple[int, str, int], everyone: bool = False) -> DraftRecord:
        """A reply to a message (to everyone on it with `everyone`), with the original quoted underneath."""
        m, account = self._original(key)
        to, cc = reply_recipients(m.sender, m.to, m.cc, account.address, everyone)
        refs = (*m.references, *([m.message_id] if m.message_id else ()))
        return DraftRecord(account.id, ", ".join(map(str, to)), ", ".join(map(str, cc)), "",
                           reply_subject(m.subject), quote(self._plain(m), m.sender.display, m.sent),
                           m.message_id, tuple(refs))

    def forward_draft(self, key: tuple[int, str, int]) -> DraftRecord:
        m, account = self._original(key)
        return DraftRecord(account.id, "", "", "", forward_subject(m.subject),
                           forwarded(self._plain(m), m.sender, m.sent, m.subject, m.to))

    def check_draft(self, draft: DraftRecord) -> None:
        """Say what is wrong with a message before it is sent (no recipient, a mistyped address)."""
        try:
            check_outgoing(parse_recipients(draft.to), parse_recipients(draft.cc), parse_recipients(draft.bcc))
        except DomainError as e:
            raise ApplicationError(str(e)) from e

    def send(self, draft: DraftRecord) -> None:
        """Send a message. Waits for the server, so run it on a worker thread. Nothing is sent when anything
        about it is wrong; a copy is kept in Sent only for accounts whose server doesn't do that by itself."""
        if self._sender is None:
            raise ApplicationError("Sending isn't available here.")
        account = next((a for a in self._store.accounts() if a.id == draft.account_id), None)
        if account is None:
            raise NotFound("That account is gone.")
        try:
            to, cc, bcc = (parse_recipients(draft.to), parse_recipients(draft.cc), parse_recipients(draft.bcc))
            check_outgoing(to, cc, bcc)
        except DomainError as e:
            raise ApplicationError(str(e)) from e
        if self._passwords is None:
            raise ApplicationError("There is nowhere safe to keep the password on this computer.")
        mail = Outgoing(Address(account.address), to, draft.subject.strip(), draft.text, cc, bcc,
                        draft.in_reply_to, draft.references)
        raw = self._sender.send(account, self._passwords.get(account.id), mail)
        if account.auth == "password":  # Gmail and Outlook file sent mail themselves; most others don't
            sent = next((f.name for f in self._store.folders(account.id) if f.role == "sent"), None)
            if sent:
                try:
                    self._source.save_sent(account, sent, raw)
                except Exception:  # noqa: BLE001 (the message is sent; a missing copy is only a pity)
                    pass

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

    def needs_fetch(self, account_id: int, folder: str, uid: int) -> bool:
        """Whether opening this message has to ask the server for its text (so the screen can wait politely)."""
        m = self._store.message(account_id, folder, uid)
        return m is not None and not m.fetched

    def is_flagged(self, key: tuple[int, str, int]) -> bool:
        m = self._store.message(*key)
        return bool(m and m.flagged)

    def prefetch(self, limit: int = 15, stop=None) -> int:
        """Download the text of the newest messages of each inbox that haven't got it, so that opening them
        is instant. A server that fails ends that account's turn; `stop()` returning True ends it all."""
        done = 0
        for account in self._store.accounts():
            inboxes = [f.name for f in self._store.folders(account.id) if f.role == "inbox"]
            for name in inboxes:
                for m in self._store.messages(account.id, name, limit):
                    if stop is not None and stop():
                        return done
                    if m.fetched:
                        continue
                    try:
                        text, html = self._source.body(account, name, m.uid, background=True)
                    except Exception:  # noqa: BLE001 (it will be fetched when the user opens it)
                        break
                    self._store.save_body(account.id, name, m.uid, text, html)
                    done += 1
        return done

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
    people = ", ".join(_first_name(a) for a in t.participants[:3])
    return ThreadRecord(t.id, last.account_id, t.subject or "(no subject)", people, last.snippet,
                        last.sent, t.unread, len(t.messages), t.flagged,
                        any(m.has_attachments for m in t.messages),
                        tuple(m.key for m in t.messages), last.sender.display, last.sender.email)


def _first_name(a) -> str:
    """"Anna Rossi" -> "Anna"; a title like "Prof." is skipped ("Prof. Rossi" -> "Rossi"); no name -> the address."""
    if not a.name:
        return a.email.split("@")[0]
    words = a.display.split()
    return next((w for w in words if not w.endswith(".")), words[0])


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
