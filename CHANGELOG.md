# Changelog

## [0.2.0] - 2026-10-27

Account setup: a welcome page and an Add account screen (address, password; the server is guessed for common providers and can be corrected). The sign-in is checked before anything is saved, the password goes to the system keyring, and an account can be removed again (its stored mail and password are forgotten; nothing changes on the server). Compact interface from the shared toolkit 0.5.0.

## [0.1.0] - 2026-10-26

First slice, read-only: folders, threaded conversations, full-text search, cleaned HTML with remote pictures
blocked, an IMAP adapter that only looks (EXAMINE / BODY.PEEK), a demo mailbox, Russian and Italian.

Packaging: a .deb and a Windows setup are built by CI and published with each release (Quay installs them). Account
setup in the UI, composing and sending are still to come.
