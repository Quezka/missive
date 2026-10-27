# Signing in with Google or Microsoft

Missive can sign in to Gmail (and Google Workspace / school accounts on Google) and to Outlook, Hotmail and
Microsoft 365 **without a password**: your browser opens, you approve Missive, and Missive keeps only a
refresh token in the system keyring. It is the standard desktop flow (OAuth 2.0 authorization code with PKCE and
a `127.0.0.1` redirect), and IMAP is then opened with XOAUTH2. Missive is still read-only.

Both providers want every app to have its own **client ID**, made by whoever runs the app. You make them once,
for free, and put them in a small file. Nothing is sent anywhere else.

## Where the client IDs go

`~/.local/share/Missive/oauth.json` (the same folder as `mail.db`):

```json
{
  "google":    {"client_id": "1234-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-..."},
  "microsoft": {"client_id": "00000000-0000-0000-0000-000000000000", "tenant": "common"}
}
```

Or environment variables, which win over the file: `MISSIVE_GOOGLE_CLIENT_ID`, `MISSIVE_GOOGLE_CLIENT_SECRET`,
`MISSIVE_MICROSOFT_CLIENT_ID`, `MISSIVE_MICROSOFT_TENANT`.

Google calls the secret of a Desktop-app client "not confidential", so a file is fine; it is still best kept
private. Restart Missive after editing. In the Add account screen, "Sign in with Google / Microsoft" is greyed out
(with a hint) until the client ID exists.

## Google

1. <https://console.cloud.google.com/> -> create a project (any name).
2. *APIs & Services -> OAuth consent screen*: user type **External**, fill the app name ("Missive") and your email.
   Under *Scopes* add `https://mail.google.com/` (Gmail IMAP needs this one; it is called a restricted scope).
3. Add your own address under *Test users*.
4. *Credentials -> Create credentials -> OAuth client ID -> Desktop app*. Copy the client ID and secret into
   `oauth.json`.

Gotchas:

- While the consent screen is in **Testing**, Google expires the refresh token after **7 days** and Missive will
  say the sign-in expired. For an app only you use, press *Publish app* (status "In production"): it stays
  unverified, so you click through Google's "hasn't verified this app" warning once, and the token no longer
  expires. (An unverified app is limited to 100 users, which is irrelevant here.)
- A school or company Google account may block third-party apps. Then ask the administrator to allow the client
  ID, or use an app password if they allow those.

## Microsoft (Outlook.com, Hotmail, Microsoft 365)

1. <https://portal.azure.com/> -> *Microsoft Entra ID -> App registrations -> New registration* (a free personal
   Microsoft account is enough).
2. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**.
3. Redirect URI: platform **Mobile and desktop applications**, value `http://localhost`.
4. *Authentication -> Allow public client flows -> Yes*.
5. *API permissions -> Add a permission -> APIs my organization uses -> Office 365 Exchange Online -> Delegated ->
   IMAP.AccessAsUser.All* (and `offline_access`, which Missive asks for). Work or school tenants may need an
   administrator to grant consent, and administrators can switch IMAP off.
6. Copy the **Application (client) ID** into `oauth.json`. `tenant` is `common` for any account, `consumers` for
   personal only, `organizations` for work or school only, or a tenant ID.

Outlook.com and Hotmail no longer accept passwords from mail programs, so this is the only way to read them.

## What Missive does and does not do

- The browser is the only place a password is typed. Missive never sees it.
- Only the refresh token is stored, in the keyring (never in `mail.db` or a file). Removing the account in
  Missive deletes it; you can also revoke Missive in your Google or Microsoft account's connected apps.
- Microsoft hands out a new refresh token now and then; Missive uses the new one for the rest of the run and
  keeps the original in the keyring, which keeps working until it has been idle for about 90 days.
- The check-in at the end of the browser step is read-only: it only lists the folders.
