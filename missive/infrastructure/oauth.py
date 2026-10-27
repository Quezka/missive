"""Signing in to Google and Microsoft mail without a password: OAuth 2.0 authorization code with PKCE and a
loopback redirect, the flow for desktop apps. The user approves in their own browser; Missive only ever sees
a refresh token, which goes to the system keyring (see passwords.py), never to the database or a file.

The client IDs belong to whoever runs Missive (see docs/OAUTH.md): they are read from the environment or from
`oauth.json` in Missive's data folder. A Google "Desktop app" client has a secret that Google itself says is
not confidential; it is read from the same place."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ..application.errors import SourceError

WAIT_SECONDS = 180  # how long to wait for the user to approve in the browser
REFRESH_MARGIN = 60  # renew an access token this many seconds before it runs out


@dataclass(frozen=True)
class ClientIds:
    client_id: str = ""
    client_secret: str = ""  # Google Desktop clients only; empty for Microsoft public clients
    tenant: str = "common"  # Microsoft: "common", "consumers", "organizations" or a tenant id


@dataclass(frozen=True)
class Endpoints:
    auth: str
    token: str
    scope: str
    redirect_host: str  # the host the browser is sent back to (always served by this computer)
    extra: tuple[tuple[str, str], ...] = ()  # more parameters for the authorization URL


def endpoints(provider: str, ids: ClientIds) -> Endpoints:
    if provider == "google":
        return Endpoints("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
                         "https://mail.google.com/", "127.0.0.1",
                         (("access_type", "offline"), ("prompt", "consent")))
    if provider == "microsoft":
        base = f"https://login.microsoftonline.com/{urllib.parse.quote(ids.tenant or 'common')}/oauth2/v2.0"
        return Endpoints(f"{base}/authorize", f"{base}/token",
                         "https://outlook.office.com/IMAP.AccessAsUser.All offline_access", "localhost")
    raise SourceError("Choose Google or Microsoft to sign in without a password.")


def load_client_ids(path: Path | None = None, environ=None) -> dict[str, ClientIds]:
    """Client IDs from `oauth.json` ({"google": {"client_id", "client_secret"}, "microsoft": {"client_id",
    "tenant"}}), overridden by MISSIVE_GOOGLE_CLIENT_ID / _SECRET and MISSIVE_MICROSOFT_CLIENT_ID / _TENANT."""
    environ = os.environ if environ is None else environ
    data: dict = {}
    if path is not None and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    out = {}
    for provider in ("google", "microsoft"):
        entry = data.get(provider) if isinstance(data.get(provider), dict) else {}
        prefix = f"MISSIVE_{provider.upper()}_"
        out[provider] = ClientIds(
            str(environ.get(prefix + "CLIENT_ID") or entry.get("client_id") or "").strip(),
            str(environ.get(prefix + "CLIENT_SECRET") or entry.get("client_secret") or "").strip(),
            str(environ.get(prefix + "TENANT") or entry.get("tenant") or "common").strip() or "common")
    return out


def _post_form(url: str, data: dict[str, str]) -> dict:
    """POST a form and read the JSON answer. An OAuth error comes back as a normal answer with an "error"."""
    request = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                     {"Accept": "application/json", "User-Agent": "Missive"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            raise SourceError(f"The sign-in server answered {e.code}.") from e
    except (OSError, ValueError) as e:
        raise SourceError(f"Couldn't reach the sign-in server: {e}") from e


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=")
    return verifier, challenge.decode("ascii")


_DONE_PAGE = ("<!doctype html><meta charset=utf-8><title>Missive</title>"
              "<body style='font-family:sans-serif;margin:3em'><h2>{title}</h2><p>{text}</p></body>")


class _Callback(BaseHTTPRequestHandler):
    """Receives the browser's redirect on 127.0.0.1 and remembers the answer on the server object."""

    def do_GET(self):  # noqa: N802 (the name http.server calls)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        got = {k: v[0] for k, v in query.items()}
        if not ({"code", "error"} & got.keys()):  # a favicon request or a stray visit: keep waiting
            self._reply(404, "Not found", "")
            return
        if not secrets.compare_digest(got.get("state", ""), self.server.expected_state):
            self._reply(400, "Wrong request", "This sign-in request isn't the one Missive started.")
            return
        self.server.answer = got
        if "error" in got:
            self._reply(200, "Not signed in", "You can close this tab and go back to Missive.")
        else:
            self._reply(200, "Signed in", "You can close this tab and go back to Missive.")

    def _reply(self, status: int, title: str, text: str):
        body = _DONE_PAGE.format(title=html.escape(title), text=html.escape(text)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # the URL carries the one-time code: keep it out of any log
        pass


class OAuthClient:
    """The OAuthClient port for Google and Microsoft. `open_url`, `post` and `clock` are replaced in tests."""

    def __init__(self, ids: dict[str, ClientIds], open_url=webbrowser.open, post=_post_form, clock=time.time,
                 wait: float = WAIT_SECONDS):
        self._ids = ids
        self._open_url = open_url
        self._post = post
        self._clock = clock
        self._wait = wait
        self._cancelled = threading.Event()
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}  # (provider, refresh token) -> (token, expires)
        self._rotated: dict[tuple[str, str], str] = {}  # a newer refresh token the server handed out this run

    def available(self, provider: str) -> bool:
        return bool(self._ids.get(provider, ClientIds()).client_id)

    def _client(self, provider: str) -> tuple[ClientIds, Endpoints]:
        ids = self._ids.get(provider, ClientIds())
        if not ids.client_id:
            raise SourceError("This sign-in isn't set up yet: add its client ID (see docs/OAUTH.md).")
        return ids, endpoints(provider, ids)

    # ---- the browser step ----

    def cancel(self) -> None:
        self._cancelled.set()

    def authorize(self, provider: str, address: str) -> str:
        ids, ep = self._client(provider)
        self._cancelled.clear()
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(24)
        try:
            server = HTTPServer(("127.0.0.1", 0), _Callback)
        except OSError as e:
            raise SourceError(f"Couldn't wait for the browser on this computer: {e}") from e
        server.expected_state, server.answer = state, None
        server.timeout = 0.5
        redirect = f"http://{ep.redirect_host}:{server.server_port}"
        params = {"client_id": ids.client_id, "redirect_uri": redirect, "response_type": "code", "scope": ep.scope,
                  "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                  "login_hint": address, **dict(ep.extra)}
        try:
            if not self._open_url(f"{ep.auth}?{urllib.parse.urlencode(params)}"):
                raise SourceError("Couldn't open your web browser.")
            deadline = self._clock() + self._wait
            while server.answer is None and not self._cancelled.is_set() and self._clock() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        answer = server.answer
        if answer is None and self._cancelled.is_set():
            raise SourceError("The sign-in was cancelled.")
        if answer is None:
            raise SourceError("Nobody signed in: the browser window wasn't answered in time.")
        if "error" in answer:
            if answer["error"] == "access_denied":
                raise SourceError("The sign-in was cancelled.")
            raise SourceError(f"Sign-in failed: {answer.get('error_description') or answer['error']}")
        data = {"client_id": ids.client_id, "code": answer["code"], "code_verifier": verifier,
                "redirect_uri": redirect, "grant_type": "authorization_code"}
        if ids.client_secret:
            data["client_secret"] = ids.client_secret
        reply = self._token_reply(self._post(ep.token, data))
        refresh = reply.get("refresh_token")
        if not refresh:
            raise SourceError("The provider didn't allow staying signed in (no refresh token). "
                              "Remove Missive from the account's connected apps and try again.")
        if reply.get("access_token"):  # the first access token is good for the check that follows
            self._remember(provider, refresh, reply)
        return refresh

    # ---- the tokens ----

    def access_token(self, provider: str, refresh_token: str) -> str:
        key = (provider, refresh_token)
        token, expires = self._cache.get(key, ("", 0.0))
        if token and self._clock() < expires - REFRESH_MARGIN:
            return token
        ids, ep = self._client(provider)
        data = {"client_id": ids.client_id, "grant_type": "refresh_token",
                "refresh_token": self._rotated.get(key, refresh_token)}
        if ids.client_secret:
            data["client_secret"] = ids.client_secret
        if provider == "microsoft":
            data["scope"] = ep.scope
        reply = self._token_reply(self._post(ep.token, data))
        if not reply.get("access_token"):
            raise SourceError("The sign-in server gave no access token.")
        self._remember(provider, refresh_token, reply)
        return reply["access_token"]

    def _remember(self, provider: str, refresh_token: str, reply: dict) -> None:
        key = (provider, refresh_token)
        self._cache[key] = (reply["access_token"], self._clock() + float(reply.get("expires_in") or 3600))
        if reply.get("refresh_token") and reply["refresh_token"] != refresh_token:
            self._rotated[key] = reply["refresh_token"]  # Microsoft hands out a new one; the old keeps working

    @staticmethod
    def _token_reply(reply: dict) -> dict:
        error = reply.get("error")
        if not error:
            return reply
        if error == "invalid_grant":
            raise SourceError("The sign-in has expired or was revoked. Remove the account and add it again.")
        raise SourceError(f"Sign-in failed: {reply.get('error_description') or error}")


def xoauth2(user: str, token: str) -> bytes:
    """The SASL XOAUTH2 initial response IMAP servers expect (imaplib adds the base64)."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()
