"""Writing mail: who a reply goes to, the quoted text, and checking what the user typed. Pure Python."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import getaddresses

from .errors import ValidationError
from .model import Address

_EMAIL = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")


@dataclass(frozen=True)
class Outgoing:
    """A message ready to send."""

    sender: Address
    to: tuple[Address, ...]
    subject: str
    text: str
    cc: tuple[Address, ...] = ()
    bcc: tuple[Address, ...] = ()
    in_reply_to: str = ""
    references: tuple[str, ...] = ()

    @property
    def recipients(self) -> tuple[Address, ...]:
        """Everyone the server must deliver to: Bcc is here but never in the headers."""
        return (*self.to, *self.cc, *self.bcc)


def parse_recipients(text: str, what: str = "") -> tuple[Address, ...]:
    """"Anna <a@x.org>, b@y.org" -> two addresses; separators are commas or semicolons. A wrong address raises,
    and so does a line break: a recipient field is one line, and a break could smuggle in a header."""
    text = text or ""
    if re.search(r"[\r\n]", text):
        raise ValidationError(f"“{' '.join(text.split())[:40]}” doesn't look like an email address.")
    found = []
    for part in text.split(";"):
        if not part.replace(",", " ").strip():  # nothing but separators
            continue
        for name, email in getaddresses([part]) or [("", "")]:
            email = email.strip()
            if not _EMAIL.match(email):
                raise ValidationError(f"“{(email or name or part).strip()}” doesn't look like an email address.")
            found.append(Address(email, name.strip()))
    return tuple(found)


def check_outgoing(to: tuple[Address, ...], cc: tuple[Address, ...], bcc: tuple[Address, ...]) -> None:
    if not (to or cc or bcc):
        raise ValidationError("Add at least one recipient.")


def _prefixed(subject: str, prefix: str) -> str:
    subject = (subject or "").strip()
    return subject if re.match(rf"^{prefix}\s*:", subject, re.I) else f"{prefix}: {subject}".rstrip(": ").strip()


def reply_subject(subject: str) -> str:
    return _prefixed(subject, "Re")


def forward_subject(subject: str) -> str:
    return _prefixed(subject, "Fwd")


def quote(text: str, who: str, when: datetime) -> str:
    """The original message under a one-line header, each line marked with "> "."""
    lines = (text or "").strip().splitlines() or [""]
    body = "\n".join(f"> {line}" if line.strip() else ">" for line in lines)
    return f"\n\nOn {when:%d %b %Y}, {when:%H:%M}, {who} wrote:\n{body}\n"


def reply_recipients(sender: Address, to: tuple[Address, ...], cc: tuple[Address, ...], me: str,
                     everyone: bool) -> tuple[tuple[Address, ...], tuple[Address, ...]]:
    """(To, Cc) of a reply: the sender; with `everyone`, also the others on the message, never the user."""
    if not everyone:
        return (sender,), ()
    mine = me.strip().lower()
    seen = {sender.email.lower(), mine}
    others_to, others_cc = [], []
    for target, source in ((others_to, to), (others_cc, cc)):
        for a in source:
            if a.email.lower() not in seen:
                seen.add(a.email.lower())
                target.append(a)
    return (sender, *others_to), tuple(others_cc)


def forwarded(text: str, sender: Address, when: datetime, subject: str, to: tuple[Address, ...]) -> str:
    head = ["---------- Forwarded message ----------", f"From: {sender}", f"Date: {when:%d %b %Y, %H:%M}",
            f"Subject: {subject}", f"To: {', '.join(str(a) for a in to)}"]
    return "\n\n" + "\n".join(head) + "\n\n" + (text or "").strip() + "\n"
