# Changelog

## [0.5.1] - 2026-10-27

Fixed: pictures in mail did not show. Qt only draws pictures from files, so pictures on the internet never appeared even after Load pictures, and pictures sent inside the message (`cid:`) were never put back. Now pictures inside a message show at once (nothing is fetched, so nothing can track you; if they sit past the first 250 KB the message is fetched again in full), and Load pictures really fetches the internet ones, scaled to the window. Fetching has hard rules: only public addresses (a message can't make your computer contact your router, your NAS or localhost), no cookies, no cache, no referrer, 15 s and 8 MB per picture, at most 40 per message, and an old request is dropped the moment you open another letter.

## [0.5.0] - 2026-10-27

Writing mail: **New message**, **Reply**, **Reply to all** and **Forward**, in a compose window that stays out of the way while you read. Send waits eight seconds with an **Undo** bar (and still sends if you close the window), then goes out over SMTP with TLS, signed in with your password or with your Google or Microsoft token (Google needs nothing new; a Microsoft account must be removed and added again once to grant the send permission). A message the server refuses comes back for you to fix, with everything you typed. Replies quote the original and keep the thread; Bcc stays out of the headers; a mistyped address is named before anything is sent. Accounts without Gmail's or Outlook's habit of filing sent mail get a copy in their Sent folder. Outgoing server settings per account (guessed for common providers). Includes everything in 0.4.2 below, which was never released on its own.

## [0.4.2] - 2026-10-27

Faster and clearer. A folder with nothing new is now skipped after one tiny question to the server instead of being opened, so checking a big Gmail takes seconds. Fetching letters ahead of time uses its own connection and the check no longer shows as busy while it does, so a letter you click never waits behind it. Only the first 250 KB of a message is downloaded. Folder names written in other alphabets (a Russian Gmail's "Спам", "Корзина", "Вся почта") are now shown properly instead of as codes. `missive --debug` (or MISSIVE_DEBUG=1) prints how long each server step takes, to find slow spots.

## [0.4.1] - 2026-10-27

(The 0.4.0 tag never produced a release: its version number had not been bumped. This is the same work, released as 0.4.1.)

Fixed: Missive no longer freezes after signing in. Checking for new mail now runs in the background (the window stays usable, with a progress bar and a status line), a mailbox's first check takes only the newest 300 messages of each folder instead of every message (a Gmail "All Mail" has tens of thousands), and one folder that can't be read no longer stops the others. Mail is checked when the app opens and every five minutes.

Faster: opening a letter used to sign in again and download the whole message with its attachments. Missive now keeps its connection open, downloads only the start of each message (the text), fetches in the background with a "Loading…" state, and pre-downloads the newest inbox mail after each check so it opens instantly.

New look: a sidebar with folder icons and unread counts, conversations with round avatars under Today / Yesterday / Last 7 days headings, a reader with the sender's avatar, name, address and date, a banner for blocked pictures, empty states, and a settings menu (appearance, high contrast, remove account). Light, dark and high contrast. Ctrl+R / F5 check for mail, Ctrl+F searches.

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
