"""Passwords live in the operating system's keyring, never in the database or a file."""
from __future__ import annotations

SERVICE = "Missive"


def keyring_passwords(account_id: int) -> str:
    try:
        import keyring
    except ImportError as e:  # the keyring package is optional until accounts are added
        raise RuntimeError("Install the 'keyring' package to read passwords from the system keyring.") from e
    secret = keyring.get_password(SERVICE, f"account-{account_id}")
    if secret is None:
        raise RuntimeError("No password saved for this account.")
    return secret
