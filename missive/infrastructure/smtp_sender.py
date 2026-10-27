"""Sending mail over SMTP, with a password or with the OAuth token of a Google or Microsoft account.

This is the only place Missive writes to the world, and only when the user has pressed Send."""
from __future__ import annotations

import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from datetime import datetime, timezone

from ..application.errors import SourceError
from ..domain import Account, Outgoing, smtp_for
from .oauth import xoauth2

TIMEOUT = 30


def build_message(account: Account, mail: Outgoing) -> EmailMessage:
    """The RFC 822 message: Bcc is left out of the headers (the server still delivers to it)."""
    msg = EmailMessage()
    domain = account.address.rsplit("@", 1)[-1]
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Date"] = format_datetime(datetime.now(timezone.utc).astimezone())
    msg["From"] = formataddr((mail.sender.name, mail.sender.email))
    msg["To"] = ", ".join(formataddr((a.name, a.email)) for a in mail.to)
    if mail.cc:
        msg["Cc"] = ", ".join(formataddr((a.name, a.email)) for a in mail.cc)
    msg["Subject"] = mail.subject
    if mail.in_reply_to:
        msg["In-Reply-To"] = mail.in_reply_to
    if mail.references:
        msg["References"] = " ".join(mail.references)
    msg.set_content(mail.text or "")
    return msg


def _reason(e: Exception) -> str:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "the server refused the sign-in (" + e.smtp_error.decode("utf-8", "replace").strip() + ")"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "the server refused these recipients: " + ", ".join(e.recipients)
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "the server refused the sender address (" + e.smtp_error.decode("utf-8", "replace").strip() + ")"
    if isinstance(e, smtplib.SMTPResponseException):
        return f"{e.smtp_code} {e.smtp_error.decode('utf-8', 'replace').strip()}"
    return str(e) or type(e).__name__


class SmtpSender:
    """MailSender over SMTP. `connect(host, port)` makes the connection (replaced in tests); `oauth` turns a
    refresh token into an access token for XOAUTH2."""

    def __init__(self, oauth=None, connect=None):
        self._oauth = oauth
        self._connect = connect or self._real_connect

    @staticmethod
    def _real_connect(host: str, port: int):
        context = ssl.create_default_context()
        if port == 465:  # TLS from the first byte
            return smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=context)
        server = smtplib.SMTP(host, port, timeout=TIMEOUT)
        server.ehlo()
        server.starttls(context=context)  # never sign in over an unencrypted connection
        server.ehlo()
        return server

    def send(self, account: Account, secret: str, mail: Outgoing) -> bytes:
        host, port = (account.smtp_host, account.smtp_port) if account.smtp_host else \
            smtp_for(account.host, account.auth, account.address)
        msg = build_message(account, mail)
        user = account.username or account.address
        started = time.monotonic()
        try:
            server = self._connect(host, port)
            try:
                if account.auth == "password":
                    server.login(user, secret)
                else:
                    if self._oauth is None:
                        raise SourceError("This sign-in isn't set up yet: add its client ID (see docs/OAUTH.md).")
                    token = self._oauth.access_token(account.auth, secret)
                    server.auth("XOAUTH2", lambda challenge=None: xoauth2(user, token).decode("ascii"),
                                initial_response_ok=True)
                server.send_message(msg, from_addr=mail.sender.email, to_addrs=[a.email for a in mail.recipients])
            finally:
                try:
                    server.quit()
                except Exception:  # noqa: BLE001
                    pass
        except SourceError:
            raise
        except (smtplib.SMTPException, OSError) as e:
            raise SourceError(f"{account.name}: couldn't send ({_reason(e)})") from e
        return msg.as_bytes()
