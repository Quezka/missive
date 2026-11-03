from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from typing import Callable

from .errors import UpdateError
from .ports import KeyValueStore, ReleaseAsset, ReleaseFeed, UpdateInstaller

CHECK_EVERY = timedelta(hours=20)


def parse_version(text: str) -> tuple[int, ...]:
    """"v0.11.0" -> (0, 11, 0); anything unparseable sorts as oldest."""
    numbers = re.findall(r"\d+", text.split("-")[0])
    return tuple(int(n) for n in numbers[:3]) if numbers else (0,)


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    current: str
    notes: str
    page_url: str
    asset: ReleaseAsset | None  # the file for this platform
    can_install: bool  # False: send the user to the download page instead


class UpdateService:
    """Use cases for updating Missive from inside the app.

    `check()` and `download()` are network only (run them on a worker thread); `install()`
    may block while the system installer runs, so it belongs on a worker thread too.
    """

    PREFIX = "updates."

    def __init__(self, feed: ReleaseFeed, installer: UpdateInstaller, settings: KeyValueStore,
                 current_version: str, now: Callable[[], datetime] = datetime.now):
        self._feed = feed
        self._installer = installer
        self._settings = settings
        self._now = now
        self.current_version = current_version

    def auto_check(self) -> bool:
        return self._settings.get(self.PREFIX + "auto") != "0"

    def set_auto_check(self, on: bool) -> None:
        self._settings.set(self.PREFIX + "auto", "1" if on else "0")

    def due(self) -> bool:
        """Time for the automatic check (about once a day)."""
        if not self.auto_check():
            return False
        last = self._settings.get(self.PREFIX + "last_check")
        return not last or self._now() - datetime.fromisoformat(last) >= CHECK_EVERY

    def mark_checked(self) -> None:
        self._settings.set(self.PREFIX + "last_check",
                           self._now().isoformat(timespec="seconds"))

    def skip(self, version: str) -> None:
        self._settings.set(self.PREFIX + "skipped", version)

    def skipped(self, version: str) -> bool:
        return self._settings.get(self.PREFIX + "skipped") == version

    def check(self) -> AvailableUpdate | None:
        """The newest release if it's newer than this copy."""
        release = self._feed.latest()
        if release is None or parse_version(release.version) <= parse_version(
                self.current_version):
            return None
        asset = self._installer.pick(release.assets)
        return AvailableUpdate(release.version, self.current_version, release.notes,
                               release.page_url, asset,
                               asset is not None and self._installer.supported())

    def download(self, update: AvailableUpdate, progress) -> str:
        if update.asset is None:
            raise UpdateError("There's no download for this computer in that release.")
        return self._feed.download(update.asset, progress)

    def install(self, path: str) -> bool:
        return self._installer.install(path)
