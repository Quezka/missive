"""Reading a real mailbox over IMAP, read-only: it only ever uses EXAMINE and BODY.PEEK, so
looking at mail here never marks it read, moves it or deletes it."""
from __future__ import annotations

import email
import email.policy
import imaplib
import re
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime

from ..application.errors import SourceError
from ..domain import Account, Address, Folder, Message, text_of
from .oauth import xoauth2

HEADER_FIELDS = "DATE FROM TO CC SUBJECT MESSAGE-ID IN-REPLY-TO REFERENCES"
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


class ImapSource:
    """MailSource over IMAP-over-TLS. `passwords` maps an account id to its secret (the OS keyring in
    the app): the password, or for a Google or Microsoft account the OAuth refresh token, which `oauth`
    turns into an access token for XOAUTH2. `connect` makes the connection (replaced in tests)."""

    def __init__(self, passwords, connect=None, oauth=None):
        self._passwords = passwords
        self._connect = connect or self._real_connect
        self._oauth = oauth

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

    def check(self, account: Account, secret: str) -> None:
        conn = self._session(account, secret)
        try:
            status, _ = conn.list()
            if status != "OK":
                raise SourceError(f"{account.name}: the server wouldn't list its folders")
        finally:
            self._close(conn)

    def folders(self, account: Account) -> list[Folder]:
        conn = self._session(account)
        try:
            status, data = conn.list()
            out = []
            for line in data or ():
                m = _LIST.match(line if isinstance(line, bytes) else line[0])
                if not m or b"\\noselect" in m["flags"].lower():
                    continue
                name = m["name"].strip().strip(b'"').decode("ascii", "replace")
                out.append(Folder(account.id, name, role_of(m["flags"].decode("ascii", "ignore"), name)))
            return out
        finally:
            self._close(conn)

    def headers(self, account: Account, folder: str, after_uid: int) -> list[Message]:
        conn = self._session(account)
        try:
            status, _ = conn.select(f'"{folder}"', readonly=True)  # EXAMINE: nothing can change
            if status != "OK":
                return []
            status, data = conn.uid("FETCH", f"{after_uid + 1}:*",
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
            return out
        finally:
            self._close(conn)

    def body(self, account: Account, folder: str, uid: int) -> tuple[str | None, str | None]:
        conn = self._session(account)
        try:
            conn.select(f'"{folder}"', readonly=True)
            status, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            for item in data or ():
                if isinstance(item, tuple):
                    text, html, _attachments = parse_body(item[1])
                    return text, html
            return None, None
        finally:
            self._close(conn)

    @staticmethod
    def _close(conn):
        try:
            conn.logout()
        except Exception:
            pass
