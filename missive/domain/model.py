"""Mail, as the rest of the app thinks of it. Pure Python: no IMAP, SQLite or Qt in here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Address:
    email: str
    name: str = ""

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email

    @property
    def display(self) -> str:
        return self.name or self.email


@dataclass(frozen=True)
class Account:
    id: int
    name: str  # what the user calls it, "School"
    address: str
    host: str
    port: int = 993
    username: str = ""
    color: str = "#5b5bd6"
    auth: str = "password"  # how it signs in: "password" (also an app password), "google" or "microsoft" (OAuth)
    smtp_host: str = ""  # where mail is sent from; empty = worked out from the provider (see providers.smtp_for)
    smtp_port: int = 587


@dataclass(frozen=True)
class Folder:
    account_id: int
    name: str  # the server's name, "INBOX", "Sent"
    role: str = ""  # "inbox", "sent", "drafts", "trash", "junk", "archive" or ""

    @property
    def key(self) -> tuple[int, str]:
        return (self.account_id, self.name)


@dataclass
class Message:
    """One message as listed: its headers and what is needed to thread and find it."""

    account_id: int
    folder: str
    uid: int
    subject: str
    sender: Address
    sent: datetime
    to: tuple[Address, ...] = ()
    cc: tuple[Address, ...] = ()
    message_id: str = ""
    in_reply_to: str = ""
    references: tuple[str, ...] = ()
    snippet: str = ""
    seen: bool = False
    flagged: bool = False
    has_attachments: bool = False
    body_text: str | None = None  # None until the body has been fetched
    body_html: str | None = None
    id: int | None = None

    @property
    def key(self) -> tuple[int, str, int]:
        return (self.account_id, self.folder, self.uid)

    @property
    def fetched(self) -> bool:
        return self.body_text is not None or self.body_html is not None


@dataclass
class Thread:
    """Messages that belong together, oldest first."""

    id: str
    messages: list[Message] = field(default_factory=list)

    @property
    def subject(self) -> str:
        return self.messages[0].subject if self.messages else ""

    @property
    def latest(self) -> Message:
        return self.messages[-1]

    @property
    def unread(self) -> int:
        return sum(1 for m in self.messages if not m.seen)

    @property
    def flagged(self) -> bool:
        return any(m.flagged for m in self.messages)

    @property
    def participants(self) -> list[Address]:
        seen, out = set(), []
        for m in self.messages:
            if m.sender.email.casefold() not in seen:
                seen.add(m.sender.email.casefold())
                out.append(m.sender)
        return out
