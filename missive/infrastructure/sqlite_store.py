"""SQLite store for accounts, folders and messages, with full-text search (FTS5)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ..domain import Account, Address, Folder, Message, text_of

SCHEMA_VERSION = 2  # 2: accounts.auth (password / google / microsoft)

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, address TEXT NOT NULL, host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 993, username TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#5b5bd6', auth TEXT NOT NULL DEFAULT 'password'
);
CREATE TABLE IF NOT EXISTS folders (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL, role TEXT NOT NULL DEFAULT '', PRIMARY KEY (account_id, name)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    folder TEXT NOT NULL, uid INTEGER NOT NULL,
    subject TEXT NOT NULL DEFAULT '', sender_email TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '', sent TEXT NOT NULL,
    recipients TEXT NOT NULL DEFAULT '[]', cc TEXT NOT NULL DEFAULT '[]',
    message_id TEXT NOT NULL DEFAULT '', in_reply_to TEXT NOT NULL DEFAULT '',
    refs TEXT NOT NULL DEFAULT '[]', snippet TEXT NOT NULL DEFAULT '',
    seen INTEGER NOT NULL DEFAULT 0, flagged INTEGER NOT NULL DEFAULT 0,
    has_attachments INTEGER NOT NULL DEFAULT 0, body_text TEXT, body_html TEXT,
    UNIQUE (account_id, folder, uid)
);
CREATE INDEX IF NOT EXISTS idx_messages_folder ON messages(account_id, folder, sent DESC);
"""


def _addresses(items) -> str:
    return json.dumps([[a.email, a.name] for a in items])


def _load_addresses(text: str) -> tuple[Address, ...]:
    return tuple(Address(e, n) for e, n in json.loads(text or "[]"))


class SqliteStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.fts = self._make_search()
        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def _migrate(self) -> None:
        """A database made before OAuth has no accounts.auth: add it (existing accounts use a password)."""
        columns = {r["name"] for r in self.conn.execute("PRAGMA table_info(accounts)")}
        if "auth" not in columns:
            self.conn.execute("ALTER TABLE accounts ADD COLUMN auth TEXT NOT NULL DEFAULT 'password'")

    def close(self):
        self.conn.close()

    def _make_search(self) -> bool:
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mail_fts USING fts5("
                              "subject, sender, body, tokenize='unicode61 remove_diacritics 2')")
            return True
        except sqlite3.OperationalError:  # this SQLite has no FTS5: search falls back to LIKE
            return False

    # ---- accounts and folders ----

    def accounts(self) -> list[Account]:
        return [Account(r["id"], r["name"], r["address"], r["host"], r["port"], r["username"], r["color"],
                        r["auth"])
                for r in self.conn.execute("SELECT * FROM accounts ORDER BY id")]

    def add_account(self, a: Account) -> Account:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO accounts (name, address, host, port, username, color, auth) VALUES (?,?,?,?,?,?,?)",
                (a.name, a.address, a.host, a.port, a.username, a.color, a.auth))
        return Account(cur.lastrowid, a.name, a.address, a.host, a.port, a.username, a.color, a.auth)

    def remove_account(self, account_id: int) -> None:
        with self.conn:
            if self.fts:
                self.conn.execute("DELETE FROM mail_fts WHERE rowid IN (SELECT id FROM messages WHERE account_id = ?)",
                                  (account_id,))
            self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))  # folders and messages cascade

    def save_folders(self, folders: list[Folder]) -> None:
        with self.conn:
            for f in folders:
                self.conn.execute("INSERT INTO folders (account_id, name, role) VALUES (?,?,?) "
                                  "ON CONFLICT(account_id, name) DO UPDATE SET role = excluded.role",
                                  (f.account_id, f.name, f.role))

    def folders(self, account_id: int | None = None) -> list[Folder]:
        rows = self.conn.execute("SELECT * FROM folders" + (" WHERE account_id = ?" if account_id else ""),
                                 (account_id,) if account_id else ()).fetchall()
        return [Folder(r["account_id"], r["name"], r["role"]) for r in rows]

    # ---- messages ----

    def max_uid(self, account_id: int, folder: str) -> int:
        row = self.conn.execute("SELECT MAX(uid) FROM messages WHERE account_id = ? AND folder = ?",
                                (account_id, folder)).fetchone()
        return row[0] or 0

    @staticmethod
    def _message(r) -> Message:
        return Message(
            r["account_id"], r["folder"], r["uid"], r["subject"], Address(r["sender_email"], r["sender_name"]),
            datetime.fromisoformat(r["sent"]), _load_addresses(r["recipients"]), _load_addresses(r["cc"]),
            r["message_id"], r["in_reply_to"], tuple(json.loads(r["refs"])), r["snippet"],
            bool(r["seen"]), bool(r["flagged"]), bool(r["has_attachments"]), r["body_text"], r["body_html"],
            r["id"])

    def save_messages(self, messages: list[Message]) -> int:
        new = 0
        with self.conn:
            for m in messages:
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO messages (account_id, folder, uid, subject, sender_email, sender_name,"
                    " sent, recipients, cc, message_id, in_reply_to, refs, snippet, seen, flagged,"
                    " has_attachments, body_text, body_html) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (m.account_id, m.folder, m.uid, m.subject, m.sender.email, m.sender.name,
                     m.sent.isoformat(), _addresses(m.to), _addresses(m.cc), m.message_id, m.in_reply_to,
                     json.dumps(list(m.references)), m.snippet, int(m.seen), int(m.flagged),
                     int(m.has_attachments), m.body_text, m.body_html))
                if cur.rowcount:
                    new += 1
                    self._index(cur.lastrowid, m.subject, f"{m.sender.name} {m.sender.email}",
                                f"{m.body_text or ''} {text_of(m.body_html or '')}".strip() or m.snippet)
        return new

    def _index(self, row_id: int, subject: str, sender: str, body: str):
        if self.fts:
            self.conn.execute("DELETE FROM mail_fts WHERE rowid = ?", (row_id,))
            self.conn.execute("INSERT INTO mail_fts (rowid, subject, sender, body) VALUES (?,?,?,?)",
                              (row_id, subject, sender, body))

    def messages(self, account_id, folder, limit):
        sql, args = "SELECT * FROM messages", []
        where = []
        if account_id is not None:
            where.append("account_id = ?"); args.append(account_id)
        if folder is not None:
            where.append("folder = ?"); args.append(folder)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY sent DESC LIMIT ?"
        return [self._message(r) for r in self.conn.execute(sql, (*args, limit))]

    def message(self, account_id, folder, uid):
        r = self.conn.execute("SELECT * FROM messages WHERE account_id = ? AND folder = ? AND uid = ?",
                              (account_id, folder, uid)).fetchone()
        return self._message(r) if r else None

    def save_body(self, account_id, folder, uid, text, html):
        with self.conn:
            self.conn.execute("UPDATE messages SET body_text = ?, body_html = ? WHERE account_id = ? "
                              "AND folder = ? AND uid = ?", (text if text is not None else "",
                                                             html, account_id, folder, uid))
            r = self.conn.execute("SELECT id, subject, sender_name, sender_email, snippet FROM messages "
                                  "WHERE account_id = ? AND folder = ? AND uid = ?",
                                  (account_id, folder, uid)).fetchone()
            if r:
                self._index(r["id"], r["subject"], f"{r['sender_name']} {r['sender_email']}",
                            f"{text or ''} {text_of(html or '')}".strip() or r["snippet"])

    def set_seen(self, account_id, folder, uid, seen):
        with self.conn:
            self.conn.execute("UPDATE messages SET seen = ? WHERE account_id = ? AND folder = ? AND uid = ?",
                              (int(seen), account_id, folder, uid))

    def set_flagged(self, account_id, folder, uid, flagged):
        with self.conn:
            self.conn.execute("UPDATE messages SET flagged = ? WHERE account_id = ? AND folder = ? AND uid = ?",
                              (int(flagged), account_id, folder, uid))

    def search(self, query: str, limit: int) -> list[Message]:
        words = [w for w in query.replace('"', " ").split() if w]
        if not words:
            return []
        if self.fts:
            match = " ".join(f'"{w}"*' for w in words)  # every word, as a prefix
            rows = self.conn.execute(
                "SELECT m.* FROM mail_fts f JOIN messages m ON m.id = f.rowid WHERE mail_fts MATCH ? "
                "ORDER BY m.sent DESC LIMIT ?", (match, limit)).fetchall()
        else:
            clause = " AND ".join("(subject LIKE ? OR sender_email LIKE ? OR sender_name LIKE ? OR "
                                  "COALESCE(body_text, snippet) LIKE ?)" for _ in words)
            args = [f"%{w}%" for w in words for _ in range(4)]
            rows = self.conn.execute(f"SELECT * FROM messages WHERE {clause} ORDER BY sent DESC LIMIT ?",
                                     (*args, limit)).fetchall()
        return [self._message(r) for r in rows]

    def unread_counts(self):
        return {(r[0], r[1]): r[2] for r in self.conn.execute(
            "SELECT account_id, folder, COUNT(*) FROM messages WHERE seen = 0 GROUP BY account_id, folder")}

    def totals(self):
        return {(r[0], r[1]): r[2] for r in self.conn.execute(
            "SELECT account_id, folder, COUNT(*) FROM messages GROUP BY account_id, folder")}
