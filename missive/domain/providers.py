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
