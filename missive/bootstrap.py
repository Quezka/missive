"""Wires the layers together: the only place that knows every concrete class."""
from __future__ import annotations

from pathlib import Path

from .application.services import MailService
from .infrastructure.demo_source import HOME, SCHOOL, DemoSender, DemoSource
from .infrastructure.oauth import OAuthClient, load_client_ids
from .infrastructure.passwords import KeyringPasswords, MemoryPasswords
from .infrastructure.sqlite_store import SqliteStore


def data_dir() -> Path:
    path = Path.home() / ".local" / "share" / "Missive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_updates(demo: bool = False):
    """Self-updates from GitHub releases; None in the demo (nothing may touch the network there)."""
    if demo:
        return None
    from . import __version__
    from .application.updates import UpdateService
    from .infrastructure.settings import JsonSettings
    from .infrastructure.updates import GitHubReleaseFeed, platform_installer

    return UpdateService(GitHubReleaseFeed("Quezka/missive", __version__), platform_installer(),
                         JsonSettings(), __version__)


def build_services(demo: bool = False, store=None, source=None, passwords=None) -> MailService:
    """The app's use cases. `--demo` runs on made-up mail in memory; nothing touches a server."""
    if demo:
        store = store or SqliteStore(":memory:")
        source = source or DemoSource()
        if not store.accounts():
            store.add_account(SCHOOL)
            store.add_account(HOME)
        service = MailService(store, source, passwords or MemoryPasswords(), sender=DemoSender())
        service.sync()
        return service
    store = store or SqliteStore(data_dir() / "mail.db")
    oauth = OAuthClient(load_client_ids(data_dir() / "oauth.json"))
    if source is None:
        from .infrastructure.imap_source import ImapSource

        source = ImapSource((passwords or KeyringPasswords()).get, oauth=oauth)
    from .infrastructure.smtp_sender import SmtpSender

    return MailService(store, source, passwords or KeyringPasswords(), oauth, SmtpSender(oauth))
