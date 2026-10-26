"""Wires the layers together: the only place that knows every concrete class."""
from __future__ import annotations

from pathlib import Path

from .application.services import MailService
from .infrastructure.demo_source import HOME, SCHOOL, DemoSource
from .infrastructure.sqlite_store import SqliteStore


def data_dir() -> Path:
    path = Path.home() / ".local" / "share" / "Missive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_services(demo: bool = False, store=None, source=None) -> MailService:
    """The app's use cases. `--demo` runs on made-up mail in memory; nothing touches a server."""
    if demo:
        store = store or SqliteStore(":memory:")
        source = source or DemoSource()
        if not store.accounts():
            store.add_account(SCHOOL)
            store.add_account(HOME)
        service = MailService(store, source)
        service.sync()
        return service
    store = store or SqliteStore(data_dir() / "mail.db")
    if source is None:
        from .infrastructure.imap_source import ImapSource
        from .infrastructure.passwords import keyring_passwords

        source = ImapSource(keyring_passwords)
    return MailService(store, source)
