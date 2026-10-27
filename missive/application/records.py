"""What the use cases hand to the screen: plain, read-only values."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccountRecord:
    id: int
    name: str
    address: str
    color: str


@dataclass(frozen=True)
class FolderRecord:
    account_id: int
    name: str
    role: str
    unread: int
    total: int
    title: str = ""  # the name to show: decoded and without its path ("Спам", not "[Gmail]/&BCEEPwQwBDw-")


@dataclass(frozen=True)
class ThreadRecord:
    id: str
    account_id: int
    subject: str
    people: str  # "Anna, Marco"
    snippet: str
    latest: datetime
    unread: int
    count: int
    flagged: bool
    has_attachments: bool
    keys: tuple[tuple[int, str, int], ...]  # (account, folder, uid) of each message, oldest first
    sender: str = ""  # who wrote the latest message, as it would be shown ("Prof. Rossi")
    sender_email: str = ""


@dataclass(frozen=True)
class MessageRecord:
    account_id: int
    folder: str
    uid: int
    subject: str
    sender: str
    sender_email: str
    to: str
    cc: str
    sent: datetime
    seen: bool
    flagged: bool
    html: str  # safe to show: scripts, forms and remote content removed
    text: str
    blocked_images: int  # remote pictures left out (tracking pixels live there)
    links: tuple[str, ...]  # where its links really go


@dataclass(frozen=True)
class SyncReport:
    new: int
    folders: int
    problems: tuple[str, ...] = ()  # folders or accounts that couldn't be read, in the user's words


@dataclass(frozen=True)
class ServerGuess:
    host: str
    port: int
    app_password: bool  # the provider wants an app-specific password
    oauth: str  # "google" or "microsoft" when the provider offers OAuth sign-in
    smtp_host: str = ""
    smtp_port: int = 587


@dataclass(frozen=True)
class AccountDraft:
    """What the account setup screen collects."""
    name: str
    address: str
    host: str
    port: int
    username: str
    password: str  # for an OAuth account: the refresh token, once the user has approved
    auth: str = "password"  # "password", "google" or "microsoft"
    smtp_host: str = ""  # where mail is sent from; empty = the provider's
    smtp_port: int = 587


@dataclass(frozen=True)
class DraftRecord:
    """A message being written: what the compose window shows and sends back."""
    account_id: int
    to: str = ""  # as typed: "Anna <a@x.org>, b@y.org"
    cc: str = ""
    bcc: str = ""
    subject: str = ""
    text: str = ""
    in_reply_to: str = ""
    references: tuple[str, ...] = ()
