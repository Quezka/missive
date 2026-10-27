# Changelog

## [0.3.0] - 2026-10-27

Sign in with Google or Microsoft in your browser, no password (OAuth 2.0 with PKCE, then IMAP XOAUTH2): Gmail and Google Workspace, Outlook.com, Hotmail and Microsoft 365. Missive keeps only a refresh token in the system keyring. The Add account screen has a "Sign in with" choice that follows the address (Outlook and Hotmail now work; a school on Google can be picked by hand). The client IDs are yours, made once for free: see docs/OAUTH.md. Gmail still works with an app password. Existing accounts keep working (the database gains an `auth` column by itself). Still read-only.

## [0.2.1] - 2026-10-27

Fixed: the compact text size now reaches labels, buttons, menus and lists too (the desktop theme was keeping them at the system's larger size), so the whole interface really is smaller.

## [0.2.0] - 2026-10-27

Account setup: a welcome page and an Add account screen (address, password; the server is guessed for common providers and can be corrected). The sign-in is checked before anything is saved, the password goes to the system keyring, and an account can be removed again (its stored mail and password are forgotten; nothing changes on the server). Compact interface from the shared toolkit 0.5.0.

## [0.1.0] - 2026-10-26

First slice, read-only: folders, threaded conversations, full-text search, cleaned HTML with remote pictures
blocked, an IMAP adapter that only looks (EXAMINE / BODY.PEEK), a demo mailbox, Russian and Italian.

Packaging: a .deb and a Windows setup are built by CI and published with each release (Quay installs them). Account
setup in the UI, composing and sending are still to come.
