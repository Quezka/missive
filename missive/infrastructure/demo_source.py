"""A made-up mailbox, so the app can be tried (and tested) without any server or account."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from ..domain import Account, Address, Folder, Message

SCHOOL = Account(0, "School", "student@school.example", "imap.school.example", color="#0066ff")
HOME = Account(0, "Home", "me@example.org", "imap.example.org", color="#30a46c")

_BODY_HTML = (
    '<p>Hi everyone,</p><p>The <b>ER diagram</b> homework is due on Friday. Please read the notes '
    'at <a href="https://school.example/notes">the course page</a> first.</p>'
    '<img src="https://tracker.example/pixel.gif" width="1" height="1">'
    '<script>alert("not here")</script><p>Thanks,<br>Prof. Rossi</p>')


def _m(account_id, folder, uid, days_ago, hour, subject, who, email, text, *, seen=True, flagged=False,
       reply_to="", refs=(), mid="", html=None, attachments=False, now=None) -> Message:
    sent = (now - timedelta(days=days_ago)).replace(hour=hour, minute=(uid * 7) % 60, second=0, microsecond=0)
    return Message(account_id, folder, uid, subject, Address(email, who), sent,
                   (Address("me@example.org", "Me"),), (), mid or f"<{account_id}-{folder}-{uid}@demo>", reply_to,
                   tuple(refs), " ".join(text.split())[:90], seen, flagged, attachments, text, html)


class DemoSource:
    """Implements the MailSource port with fixed sample mail."""

    def __init__(self, now: datetime | None = None):
        self.now = now or datetime.now()

    def check(self, account: Account, password: str) -> None:
        pass  # the demo accepts anything

    def save_sent(self, account: Account, folder: str, raw: bytes) -> None:
        pass

    def folders(self, account: Account) -> list[Folder]:
        return [Folder(account.id, "INBOX", "inbox"), Folder(account.id, "Sent", "sent"),
                Folder(account.id, "Archive", "archive")]

    def _all(self, account: Account) -> list[Message]:
        n, a = self.now, account.id
        if account.name == "School":
            return [
                _m(a, "INBOX", 1, 6, 9, "ER diagram homework", "Prof. Rossi", "rossi@school.example",
                   "Hi everyone, the ER diagram homework is due on Friday.", seen=False,
                   mid="<hw1@school>", html=_BODY_HTML, now=n),
                _m(a, "INBOX", 2, 5, 14, "Re: ER diagram homework", "Giulia", "giulia@school.example",
                   "Can we use crow's foot notation or only Chen?", reply_to="<hw1@school>", refs=("<hw1@school>",),
                   mid="<hw2@school>", now=n),
                _m(a, "INBOX", 3, 5, 16, "Re: ER diagram homework", "Prof. Rossi", "rossi@school.example",
                   "Both are fine, as long as you say which one you used.", reply_to="<hw2@school>",
                   refs=("<hw1@school>", "<hw2@school>"), mid="<hw3@school>", seen=False, now=n),
                _m(a, "INBOX", 4, 2, 11, "Class trip: permission slip", "Secretary", "office@school.example",
                   "Please return the signed permission slip by Monday.", seen=False, flagged=True,
                   attachments=True, now=n),
                _m(a, "INBOX", 5, 1, 8, "Timetable change for Thursday", "Vice principal", "vp@school.example",
                   "Thursday's first lesson moves to room B12.", seen=False, now=n),
                _m(a, "Sent", 1, 5, 15, "Re: ER diagram homework", "Me", "me@example.org",
                   "Thank you, I'll use Chen.", reply_to="<hw3@school>", refs=("<hw1@school>",), now=n),
            ]
        return [
            _m(a, "INBOX", 1, 3, 10, "Your parcel is on its way", "Post Office", "noreply@post.example",
               "Your parcel will arrive on Thursday between 9 and 12.", seen=False, now=n),
            _m(a, "INBOX", 2, 1, 19, "Dinner on Saturday?", "Marco", "marco@example.org",
               "We're thinking pizza at 8. Are you in?", seen=False, flagged=True, now=n),
            _m(a, "INBOX", 3, 0, 7, "Weekly newsletter", "Maker Weekly", "news@maker.example",
               "This week: a coin sorter built on a Raspberry Pi.", seen=False, now=n),
            _m(a, "Archive", 1, 30, 12, "Receipt for your order", "Shop", "orders@shop.example",
               "Thank you for your order.", now=n),
        ]

    def headers(self, account: Account, folder: str, after_uid: int) -> list[Message]:
        # Like a real server, listing messages doesn't send their bodies.
        return [replace(m, body_text=None, body_html=None) for m in self._all(account)
                if m.folder == folder and m.uid > after_uid]

    def body(self, account: Account, folder: str, uid: int, background: bool = False) -> tuple[str | None, str | None]:
        m = next((x for x in self._all(account) if x.folder == folder and x.uid == uid), None)
        return (m.body_text, m.body_html) if m else (None, None)


class DemoSender:
    """Sends nothing, anywhere: the demo only pretends, so nobody can be mailed by trying the app."""

    def __init__(self):
        self.sent = []

    def send(self, account, secret, mail) -> bytes:
        self.sent.append(mail)
        return b""
