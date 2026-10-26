"""Print the CHANGELOG section for one version (used as the GitHub release body).

    python scripts/release_notes.py 0.2.0
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def notes_for(version: str, text: str | None = None) -> str:
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text,
                      re.MULTILINE | re.DOTALL)
    if not match or not match.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return match.group(1).strip()


if __name__ == "__main__":
    print(notes_for(sys.argv[1]))
