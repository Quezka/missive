"""Passwords live in the operating system's keyring, never in the database or a file."""
from __future__ import annotations

SERVICE = "Missive"


def _keyring():
    try:
        import keyring
    except ImportError as e:  # the keyring package ships with Missive, but a source install may lack it
        raise RuntimeError("Install the 'keyring' package to keep passwords in the system keyring.") from e
    return keyring


class KeyringPasswords:
    def get(self, account_id: int) -> str:
        secret = _keyring().get_password(SERVICE, f"account-{account_id}")
        if secret is None:
            raise RuntimeError("No password saved for this account.")
        return secret

    def set(self, account_id: int, password: str) -> None:
        _keyring().set_password(SERVICE, f"account-{account_id}", password)

    def delete(self, account_id: int) -> None:
        _keyring().delete_password(SERVICE, f"account-{account_id}")


class MemoryPasswords:
    """For the demo and the tests: nothing is saved anywhere."""

    def __init__(self):
        self._secrets: dict[int, str] = {}

    def get(self, account_id: int) -> str:
        return self._secrets[account_id]

    def set(self, account_id: int, password: str) -> None:
        self._secrets[account_id] = password

    def delete(self, account_id: int) -> None:
        self._secrets.pop(account_id, None)


def keyring_passwords(account_id: int) -> str:  # the old function form, kept for callers
    return KeyringPasswords().get(account_id)
