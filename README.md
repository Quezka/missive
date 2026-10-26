# Missive

A calm, fast, private mail client in the style of the Quire suite (Quire, Ligature, Gantry…).

**Status: 0.1.0, a first slice.** It reads mail, read-only, from IMAP accounts and from a built-in demo
mailbox. It does not send, delete, move or mark anything on a server. Nothing here has been run against
a real mailbox yet.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/missive --demo      # made-up mail, in memory: no server, nothing saved
```

## What it does now

- Three panes: folders (with a unified "All inboxes"), conversations, and the message.
- Conversations are threaded by `In-Reply-To` / `References`, falling back to the subject.
- Fast offline search over everything fetched (SQLite FTS5: subjects, senders, bodies, prefixes).
- HTML mail is cleaned before it is shown: no scripts, forms or styles; **remote pictures are not loaded**
  (they are how senders know you opened a message) until you press "Load pictures"; every link is shown
  with its real address and asks before it opens.
- The IMAP adapter only uses `EXAMINE` and `BODY.PEEK`, so looking at mail never marks it read.
- Russian and Italian translations, like the rest of the suite.

## Not yet (see CHANGELOG for the plan)

Adding accounts from the UI (the keyring plumbing is there), writing and sending, undo-send, snooze,
rules, keyboard shortcuts, OAuth for Google and Microsoft, suite integration (mail → Quire task, invite →
Quire event, "Edit in Ligature"), packaging (.deb, Windows installer), an Android app.

## Architecture

Same Clean Architecture as Quire: `domain` (pure mail rules) → `application` (use cases, ports, records) →
`infrastructure` (SQLite store, IMAP source, demo source, keyring) and `presentation` (Qt), wired in
`bootstrap.py`. `tests/test_architecture.py` enforces the import rules.

Passwords live in the operating system's keyring, never in the database.

## Licence

GPL-3.0-or-later.
