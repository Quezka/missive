"""Grouping messages into conversations, the way mail clients do: by the message ids that
replies point back to, falling back to the subject with "Re:" and "Fwd:" removed."""
from __future__ import annotations

import re

from .model import Message, Thread

_PREFIX = re.compile(r"^\s*((re|fwd?|r|i|aw|wg|sv)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)


def base_subject(subject: str) -> str:
    return _PREFIX.sub("", subject or "").strip()


def _subject_key(m: Message) -> str:
    return re.sub(r"\s+", " ", base_subject(m.subject)).casefold()


def group(messages: list[Message]) -> list[Thread]:
    """Threads, newest activity first. Messages are joined when one names the other in
    In-Reply-To / References, or (for messages that name nothing at all) share a subject."""
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.setdefault(i, i) != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int):
        parent[find(a)] = find(b)

    by_id: dict[str, int] = {}
    for i, m in enumerate(messages):
        if m.message_id:
            by_id.setdefault(m.message_id, i)
    by_subject: dict[str, int] = {}
    for i, m in enumerate(messages):
        find(i)
        linked = False
        for ref in (*m.references, m.in_reply_to):
            if ref and ref in by_id and by_id[ref] != i:
                union(i, by_id[ref])
                linked = True
        # A reply with no usable references (some clients strip them) still joins its subject.
        if not linked and _PREFIX.match(m.subject or "") and _subject_key(m):
            if _subject_key(m) in by_subject:
                union(i, by_subject[_subject_key(m)])
        by_subject.setdefault(_subject_key(m), i)

    groups: dict[int, list[Message]] = {}
    for i, m in enumerate(messages):
        groups.setdefault(find(i), []).append(m)
    threads = []
    for members in groups.values():
        members.sort(key=lambda m: m.sent)
        first = members[0]
        threads.append(Thread(first.message_id or f"{first.account_id}:{first.folder}:{first.uid}", members))
    threads.sort(key=lambda t: t.latest.sent, reverse=True)
    return threads
