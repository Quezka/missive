"""Folder names as the server spells them (IMAP modified UTF-7: "&BCEEPwQwBDw-") and as people read them."""
from __future__ import annotations

import base64


def decode_mailbox_name(name: str) -> str:
    """"&BCEEPwQwBDw-" -> "Спам". A name that isn't valid modified UTF-7 comes back as it was."""
    out: list[str] = []
    i = 0
    try:
        while i < len(name):
            if name[i] != "&":
                out.append(name[i])
                i += 1
                continue
            end = name.index("-", i)
            chunk = name[i + 1:end]
            if not chunk:
                out.append("&")  # "&-" is a literal ampersand
            else:
                out.append(base64.b64decode(chunk.replace(",", "/") + "=" * (-len(chunk) % 4)).decode("utf-16-be"))
            i = end + 1
    except (ValueError, UnicodeDecodeError):
        return name
    return "".join(out)


def display_name(name: str) -> str:
    """The last part of a folder's path, readable: "[Gmail]/&BCEEPwQwBDw-" -> "Спам"."""
    return decode_mailbox_name(name.rsplit("/", 1)[-1])
