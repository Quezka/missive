"""Missive's own small settings file (the UI's QSettings hold window and view choices)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "Missive"


class JsonSettings:
    def __init__(self, path: Path | None = None):
        self._path = path or config_dir() / "settings.json"

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, key: str) -> str | None:
        value = self._read().get(key)
        return None if value is None else str(value)

    def set(self, key: str, value: str | None) -> None:
        data = self._read()
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError:
            pass  # a setting that can't be saved isn't worth stopping for


class MemorySettings:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value
