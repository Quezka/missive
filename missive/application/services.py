from __future__ import annotations

from dataclasses import dataclass

from ..domain import Account, Message, clean_html, group, link_targets, text_of
from .errors import NotFound, SourceError
from .ports import MailSource, MessageStore
from .records import AccountRecord, FolderRecord, MessageRecord, SyncReport, ThreadRecord

PER_FOLDER = 200  # how many of the newest messages a folder shows


class MailService:
    """Use cases for reading mail: fetch what's new, list conversations, open a message."""

    def __init__(self, store: MessageStore, source: MailSource):
        self._store = store
        self._source = source

    # ---- accounts and folders ----

    def accounts(self) -> list[AccountRecord]:
        return [AccountRecord(a.id, a.name, a.address, a.color) for a in self._store.accounts()]

    def add_account(self, account: Account) -> AccountRecord:
        saved = self._store.add_account(account)
        return AccountRecord(saved.id, saved.name, saved.address, saved.color)

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
