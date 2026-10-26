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


@dataclass(frozen=True)
class ServerGuess:
    host: str
    port: int
    app_password: bool  # the provider wants an app-specific password
    unsupported: str  # "oauth" when the provider only allows OAuth sign-in


@dataclass(frozen=True)
class AccountDraft:
    """What the account setup screen collects."""
    name: str
    address: str
    host: str
    port: int
    username: str
    password: str
