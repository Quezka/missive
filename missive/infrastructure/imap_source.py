"""Reading a real mailbox over IMAP, read-only: it only ever uses EXAMINE and BODY.PEEK, so
looking at mail here never marks it read, moves it or deletes it."""
from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime

from ..application.errors import SourceError
from ..domain import Account, Address, Folder, Message, text_of
from .oauth import xoauth2

log = logging.getLogger("missive.imap")  # MISSIVE_DEBUG=1 shows where the time goes

HEADER_FIELDS = "DATE FROM TO CC SUBJECT MESSAGE-ID IN-REPLY-TO REFERENCES"
BODY_LIMIT = 250_000  # bytes of a message to download: the text comes first, a big attachment isn't needed to read
FIRST_SYNC = 300  # a folder's first sync takes only its newest messages (a Gmail "All Mail" has tens of thousands)
ROLES = {"\\inbox": "inbox", "\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash",
         "\\junk": "junk", "\\archive": "archive", "\\all": "archive"}
_LIST = re.compile(rb'\((?P<flags>[^)]*)\)\s+(?P<delim>"[^"]*"|NIL)\s+(?P<name>.+)')


def _addresses(value) -> tuple[Address, ...]:
    return tuple(Address(addr, name) for name, addr in getaddresses([str(value or "")]) if addr)


def _date(value) -> datetime:
    try:
        d = parsedate_to_datetime(str(value))
        return d.astimezone().replace(tzinfo=None) if d.tzinfo else d
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).astimezone().replace(tzinfo=None)


def _ids(value) -> tuple[str, ...]:
    return tuple(re.findall(r"<[^<>\s]+>", str(value or "")))


def parse_headers(account_id: int, folder: str, uid: int, flags: str, raw: bytes) -> Message:
    h = email.message_from_bytes(raw, policy=email.policy.default)
    sender = _addresses(h["From"])
    return Message(
        account_id, folder, uid, str(h["Subject"] or "").strip(), sender[0] if sender else Address("unknown"),
        _date(h["Date"]), _addresses(h["To"]), _addresses(h["Cc"]), (_ids(h["Message-ID"]) or ("",))[0],
        (_ids(h["In-Reply-To"]) or ("",))[0], _ids(h["References"]), "", "\\Seen" in flags,
        "\\Flagged" in flags)


def parse_body(raw: bytes) -> tuple[str | None, str | None, bool]:
    """(plain text, HTML, has attachments) of a whole message."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    text = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    attachments = any(True for _ in msg.iter_attachments())
    plain = text.get_content() if text is not None else None
    markup = html.get_content() if html is not None else None
    if plain is None and markup is not None:
        plain = text_of(markup)
    return plain, markup, attachments


def role_of(flags: str, name: str) -> str:
    for flag in flags.lower().split():
        if flag in ROLES:
            return ROLES[flag]
    return "inbox" if name.upper() == "INBOX" else ""


def _reason(e: Exception) -> str:
    """A server's or network's complaint, as plain text."""
    if isinstance(e, imaplib.IMAP4.error):
        text = e.args[0] if e.args else ""
        return (text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text)) or "sign-in refused"
    return str(e) or type(e).__name__


class _Slot:
    """One kept-open connection to one account for one purpose, used by one thread at a time."""

    def __init__(self):
        self.lock = threading.Lock()
        self.conn = None
        self.folder = None  # the folder selected on it, so asking again for the same one costs nothing


class ImapSource:
    """MailSource over IMAP-over-TLS. `passwords` maps an account id to its secret (the OS keyring in
    the app): the password, or for a Google or Microsoft account the OAuth refresh token, which `oauth`
    turns into an access token for XOAUTH2. `connect` makes the connection (replaced in tests)."""

    def __init__(self, passwords, connect=None, oauth=None):
        self._passwords = passwords
        self._connect = connect or self._real_connect
        self._oauth = oauth
        self._slots: dict[tuple[int, str], _Slot] = {}
        self._slots_lock = threading.Lock()

    @staticmethod
    def _real_connect(account: Account):
        return imaplib.IMAP4_SSL(account.host, account.port)

    def _session(self, account: Account, secret: str | None = None):
        conn = None
        try:
            conn = self._connect(account)
            secret = self._passwords(account.id) if secret is None else secret
            user = account.username or account.address
            if account.auth == "password":
                conn.login(user, secret)
            else:
                if self._oauth is None:
                    raise SourceError("This sign-in isn't set up yet: add its client ID (see docs/OAUTH.md).")
                token = self._oauth.access_token(account.auth, secret)
                conn.authenticate("XOAUTH2", lambda _challenge: xoauth2(user, token))
            return conn
        except (imaplib.IMAP4.error, OSError) as e:
            if conn is not None:
                self._close(conn)
            raise SourceError(f"{account.name}: {_reason(e)}") from e

    @contextmanager
    def _kept(self, account: Account, purpose: str):
        """A signed-in connection that stays open between calls (a login takes seconds; opening a message
        shouldn't). "sync" and "read" are separate, so reading a message never waits for a long sync. A
        connection the server dropped is replaced; one that failed mid-call is thrown away."""
        with self._slots_lock:
            slot = self._slots.setdefault((account.id, purpose), _Slot())
        with slot.lock:
            if slot.conn is not None:
                try:
                    slot.conn.noop()  # also lets the server tell us about new mail
                except Exception:  # noqa: BLE001 (any way a dead connection can fail)
                    self._close(slot.conn)
                    slot.conn, slot.folder = None, None
            if slot.conn is None:
                started = time.monotonic()
                slot.conn, slot.folder = self._session(account), None
                log.debug("%s: new %s connection and sign-in took %.2fs", account.name, purpose,
                          time.monotonic() - started)
            try:
                yield slot
            except Exception:
                self._close(slot.conn)
                slot.conn, slot.folder = None, None
                raise

    def close(self) -> None:
        """Sign out of every kept connection (the app is closing)."""
        with self._slots_lock:
            slots, self._slots = list(self._slots.values()), {}
        for slot in slots:
            if slot.conn is not None:
                self._close(slot.conn)

    @staticmethod
    def _examine(slot: _Slot, folder: str) -> bool:
        """Open a folder read-only on this connection (EXAMINE), unless it is open already."""
        if slot.folder != folder:
            status, _ = slot.conn.select(f'"{folder}"', readonly=True)
            slot.folder = folder if status == "OK" else None
        return slot.folder == folder

    def check(self, account: Account, secret: str) -> None:
        conn = self._session(account, secret)
        try:
            status, _ = conn.list()
            if status != "OK":
                raise SourceError(f"{account.name}: the server wouldn't list its folders")
        finally:
            self._close(conn)

    def folders(self, account: Account) -> list[Folder]:
        with self._kept(account, "sync") as slot:
            status, data = slot.conn.list()
            out = []
            for line in data or ():
                m = _LIST.match(line if isinstance(line, bytes) else line[0])
                if not m or b"\\noselect" in m["flags"].lower():
                    continue
                name = m["name"].strip().strip(b'"').decode("ascii", "replace")
                out.append(Folder(account.id, name, role_of(m["flags"].decode("ascii", "ignore"), name)))
            return out

    @staticmethod
    def _uid_next(conn, folder: str) -> int | None:
        """The UID the folder will give its next message, from one cheap STATUS (None if the server won't say)."""
        try:
            status, data = conn.status(f'"{folder}"', "(UIDNEXT)")
            match = re.search(rb"UIDNEXT (\d+)", data[0] if data and isinstance(data[0], bytes) else b"")
            return int(match.group(1)) if status == "OK" and match else None
        except Exception:  # noqa: BLE001 (an optimisation only: without it the folder is simply looked at)
            return None

    def headers(self, account: Account, folder: str, after_uid: int) -> list[Message]:
        started = time.monotonic()
        with self._kept(account, "sync") as slot:
            if after_uid > 0:
                upcoming = self._uid_next(slot.conn, folder)
                if upcoming is not None and upcoming - 1 <= after_uid:  # nothing new: no need to even open it
                    log.debug("%s / %s: nothing new (%.2fs)", account.name, folder, time.monotonic() - started)
                    return []
            if not self._examine(slot, folder):  # EXAMINE: nothing can change
                return []
            if after_uid == 0:
                after_uid = self._first_after(slot.conn)
            status, data = slot.conn.uid("FETCH", f"{after_uid + 1}:*",
                                         f"(FLAGS BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])")
            out = []
            for item in data or ():
                if not isinstance(item, tuple):
                    continue
                meta = item[0].decode("ascii", "ignore")
                uid = int(re.search(r"UID (\d+)", meta).group(1)) if "UID" in meta else 0
                if uid <= after_uid:  # "n:*" always includes the newest, even when it isn't new
                    continue
                flags = re.search(r"FLAGS \(([^)]*)\)", meta)
                out.append(parse_headers(account.id, folder, uid, flags.group(1) if flags else "", item[1]))
            log.debug("%s / %s: %d new header(s) in %.2fs", account.name, folder, len(out), time.monotonic() - started)
            return out

    @staticmethod
    def _first_after(conn) -> int:
        """The UID to fetch after on a first sync, so that about FIRST_SYNC messages come back."""
        status, data = conn.uid("SEARCH", None, "ALL")
        uids = [int(u) for u in (data[0] if data and data[0] else b"").split()] if status == "OK" else []
        return uids[-FIRST_SYNC - 1] if len(uids) > FIRST_SYNC else 0

    def body(self, account: Account, folder: str, uid: int,
             background: bool = False) -> tuple[str | None, str | None]:
        started = time.monotonic()
        # Fetching ahead has its own connection, so a letter the user clicks never waits behind it.
        with self._kept(account, "prefetch" if background else "read") as slot:
            if not self._examine(slot, folder):
                return None, None
            # Only the first BODY_LIMIT bytes: the text and HTML come first, a big attachment would just be slow.
            status, data = slot.conn.uid("FETCH", str(uid), f"(BODY.PEEK[]<0.{BODY_LIMIT}>)")
            for item in data or ():
                if isinstance(item, tuple):
                    text, html, _attachments = parse_body(item[1])
                    log.debug("%s / %s: letter %d (%d bytes) in %.2fs%s", account.name, folder, uid, len(item[1]),
                              time.monotonic() - started, " (ahead)" if background else "")
                    return text, html
            return None, None

    @staticmethod
    def _close(conn):
        try:
            conn.logout()
        except Exception:
            pass
