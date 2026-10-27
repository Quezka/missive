# Missive

Python 3.10+ / PySide6 desktop mail client (Linux + Windows), sibling of Quire (`../quire`), Ligature and
Gantry: same look, toolkit and release process. Started 2026-10-26.

- Layers: `missive/domain` → `missive/application` → `missive/infrastructure` + `missive/presentation`; wired in `missive/bootstrap.py`. `tests/test_architecture.py` enforces it.
- Run: `.venv/bin/missive --demo`. Test: `.venv/bin/python -m pytest -q` (UI tests run offscreen).
- **Safety: never point this at a real mailbox without the user saying so, and never send, move, delete or mark real mail.** Test against `DemoSource` or a fake IMAP object (`tests/test_imap.py`). The IMAP adapter is read-only (EXAMINE, BODY.PEEK); keep it so until sending is a deliberate feature.
- Passwords: OS keyring only (`infrastructure/passwords.py`), never the database or a file. For Google/Microsoft accounts (`Account.auth`) the keyring holds the OAuth refresh token; `infrastructure/oauth.py` does the browser flow + token refresh and `imap_source.py` signs in with XOAUTH2. Client IDs are the user's own (`docs/OAUTH.md`, `~/.local/share/Missive/oauth.json`). Tests use fakes only (fake browser, fake token server, fake IMAP): never run the flow against a real account without the user's say-so.
- HTML mail: `domain/sanitize.py` is an allow-list cleaner; remote pictures are blocked unless the user loads them. Don't render mail with a web engine (it would add ~150 MB and run scripts).
- UI text: wrap in `_()`/`N_()` and add Russian and Italian to `presentation/locales/ru.py` and `it.py` (`tests/test_i18n.py` checks).
- The presentation toolkit (`theme`, `icons`, `i18n`, `uiscale`, `fit`, `leave_on_enter`, `views/common`) was copied from Ligature; fix bugs in all copies (see the suite note in claude-memory).
- Commit as arsdom15@gmail.com. Releases follow Quire's policy (bump `__version__`, CHANGELOG, tag `vX.Y.Z`) once packaging exists.
