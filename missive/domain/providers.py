"""Where common mail providers keep their IMAP server, so the user only types an address."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Server:
    host: str
    port: int = 993
    app_password: bool = False  # the provider wants an app-specific password, not the account's own
    oauth: str = ""  # "google" or "microsoft" when the provider offers OAuth sign-in (the better way)


# Where mail is sent from: (host, port). 465 is TLS from the start, 587 starts plain and upgrades (STARTTLS).
SMTP_SERVERS = {
    "imap.gmail.com": ("smtp.gmail.com", 465), "imap.mail.me.com": ("smtp.mail.me.com", 587),
    "imap.mail.yahoo.com": ("smtp.mail.yahoo.com", 465), "imap.fastmail.com": ("smtp.fastmail.com", 465),
    "imap.yandex.com": ("smtp.yandex.com", 465), "imap.mail.ru": ("smtp.mail.ru", 465),
    "outlook.office365.com": ("smtp-mail.outlook.com", 587), "imapmail.libero.it": ("smtp.libero.it", 465),
    "box.virgilio.it": ("smtp.virgilio.it", 465), "imap.tiscali.it": ("smtp.tiscali.it", 465),
    "imaps.aruba.it": ("smtps.aruba.it", 465), "imap.gmx.com": ("mail.gmx.com", 587),
    "imap.gmx.net": ("mail.gmx.net", 587), "imap.mail.com": ("smtp.mail.com", 587),
    "imap.zoho.com": ("smtp.zoho.com", 465),
}
OAUTH_SMTP = {"google": ("smtp.gmail.com", 465), "microsoft": ("smtp.office365.com", 587)}  # signed-in accounts


def smtp_for(imap_host: str, auth: str = "password", address: str = "") -> tuple[str, int]:
    """Where to send from, given an account's IMAP server: the provider's own, else `smtp.` in place of `imap.`.
    A Microsoft sign-in on a company domain uses Microsoft 365's server; Outlook.com and Hotmail use theirs."""
    if auth == "microsoft" and (domain_of(address) or "") not in PROVIDERS:
        return OAUTH_SMTP["microsoft"]
    if auth == "google":
        return OAUTH_SMTP["google"]
    host = imap_host.strip().lower()
    if host in SMTP_SERVERS:
        return SMTP_SERVERS[host]
    return (re.sub(r"^imaps?\.", "smtp.", host) if re.match(r"^imaps?\.", host) else f"smtp.{host}"), 587


AUTH_METHODS = ("password", "google", "microsoft")
OAUTH_HOSTS = {"google": "imap.gmail.com", "microsoft": "outlook.office365.com"}  # for custom domains on them


PROVIDERS: dict[str, Server] = {
    "gmail.com": Server("imap.gmail.com", app_password=True, oauth="google"),
    "googlemail.com": Server("imap.gmail.com", app_password=True, oauth="google"),
    "icloud.com": Server("imap.mail.me.com", app_password=True),
    "me.com": Server("imap.mail.me.com", app_password=True),
    "mac.com": Server("imap.mail.me.com", app_password=True),
    "yahoo.com": Server("imap.mail.yahoo.com", app_password=True),
    "yahoo.it": Server("imap.mail.yahoo.com", app_password=True),
    "fastmail.com": Server("imap.fastmail.com", app_password=True),
    "yandex.com": Server("imap.yandex.com", app_password=True),
    "yandex.ru": Server("imap.yandex.com", app_password=True),
    "ya.ru": Server("imap.yandex.com", app_password=True),
    "mail.ru": Server("imap.mail.ru", app_password=True),
    "inbox.ru": Server("imap.mail.ru", app_password=True),
    "bk.ru": Server("imap.mail.ru", app_password=True),
    "list.ru": Server("imap.mail.ru", app_password=True),
    **{d: Server("outlook.office365.com", oauth="microsoft")
       for d in ("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.it", "hotmail.it", "live.it",
                 "outlook.fr", "hotmail.fr", "outlook.de", "hotmail.de", "outlook.es", "hotmail.es")},
    "libero.it": Server("imapmail.libero.it"),
    "virgilio.it": Server("box.virgilio.it"),
    "tiscali.it": Server("imap.tiscali.it"),
    "aruba.it": Server("imaps.aruba.it"),
    "gmx.com": Server("imap.gmx.com"),
    "gmx.net": Server("imap.gmx.net"),
    "mail.com": Server("imap.mail.com"),
    "zoho.com": Server("imap.zoho.com", app_password=True),
}

_ADDRESS = re.compile(r"^[^@\s]+@([^@\s.]+(?:\.[^@\s.]+)+)$")


def domain_of(address: str) -> str | None:
    match = _ADDRESS.match(address.strip())
    return match.group(1).lower() if match else None


def valid_address(address: str) -> bool:
    return domain_of(address) is not None


def guess_server(address: str) -> Server | None:
    """The server for an address: a known provider's, else the usual `imap.<domain>` (a guess the user
    can correct). None when the address isn't one."""
    domain = domain_of(address)
    if domain is None:
        return None
    return PROVIDERS.get(domain) or Server(f"imap.{domain}")
