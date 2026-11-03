"""Updating Missive from GitHub releases: the feed, and an installer per platform.

- Linux (.deb installed in /opt/missive): the new .deb is installed with `pkexec apt`, which
  asks for your password in a normal system dialog; then Missive restarts.
- Windows (installed with the setup wizard): the new setup runs silently; it closes Missive,
  upgrades it in place and starts it again.
- Anything else (running from source, a portable build): the update dialog links to the
  release page instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from ..application.errors import UpdateError
from ..application.ports import ReleaseAsset, ReleaseInfo

API = "https://api.github.com/repos/{repo}/releases/latest"
CHUNK = 256 * 1024


class GitHubReleaseFeed:
    def __init__(self, repo: str, version: str, opener: Callable = urllib.request.urlopen,
                 folder: Path | None = None, timeout: float = 30):
        self._repo = repo
        self._headers = {"Accept": "application/vnd.github+json",
                         "User-Agent": f"Missive/{version}"}
        self._open = opener
        self._folder = folder
        self._timeout = timeout

    def latest(self) -> ReleaseInfo | None:
        request = urllib.request.Request(API.format(repo=self._repo), headers=self._headers)
        try:
            with self._open(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 404:  # no release yet, or the repository isn't public
                return None
            if e.code in (403, 429):
                raise UpdateError("GitHub is limiting update checks right now: try again "
                                  "in an hour.") from e
            raise UpdateError(f"GitHub answered with an error ({e.code}).") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise UpdateError("Can't reach GitHub to check for updates. Check your internet "
                              "connection.") from e
        except ValueError as e:
            raise UpdateError("GitHub sent an answer Missive doesn't understand.") from e
        if data.get("draft") or data.get("prerelease"):
            return None
        assets = []
        for a in data.get("assets", []):
            digest = a.get("digest") or ""
            assets.append(ReleaseAsset(a["name"], a["browser_download_url"], int(a["size"]),
                                       digest.split(":", 1)[1] if digest.startswith("sha256:")
                                       else None))
        return ReleaseInfo(data["tag_name"].lstrip("v"), data.get("body") or "",
                           data.get("html_url", ""), tuple(assets))

    def download(self, asset: ReleaseAsset, progress) -> str:
        folder = self._folder or Path(tempfile.gettempdir()) / "missive-update"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / Path(asset.name).name
        partial = target.with_name(target.name + ".part")
        request = urllib.request.Request(asset.url, headers={"User-Agent":
                                                             self._headers["User-Agent"]})
        digest, done = hashlib.sha256(), 0
        try:
            with self._open(request, timeout=self._timeout) as response, \
                    open(partial, "wb") as out:
                while chunk := response.read(CHUNK):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    progress(done, asset.size)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            partial.unlink(missing_ok=True)
            raise UpdateError("The download didn't finish. Check your internet connection "
                              "and try again.") from e
        if done != asset.size or (asset.sha256 and digest.hexdigest() != asset.sha256.lower()):
            partial.unlink(missing_ok=True)
            raise UpdateError("The download was damaged (its checksum doesn't match), so it "
                              "wasn't installed. Try again.")
        partial.replace(target)
        return str(target)


def deb_architecture() -> str:
    machine = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine)


class DebInstaller:
    """For the .deb build, which lives in /opt/missive."""

    PREFIX = Path("/opt/missive")

    def __init__(self, executable: str | None = None, runner: Callable = subprocess.run):
        self._executable = Path(executable or sys.executable)
        self._run = runner

    def supported(self) -> bool:
        return (getattr(sys, "frozen", False) and self._executable.resolve().is_relative_to(
            self.PREFIX) and shutil.which("pkexec") is not None)

    def pick(self, assets):
        suffix = f"_{deb_architecture()}.deb"
        return next((a for a in assets if a.name.endswith(suffix)), None)

    def install(self, path: str) -> bool:
        # pkexec shows the system's password dialog; apt checks the package and upgrades.
        result = self._run(["pkexec", "apt-get", "install", "-y", "--allow-downgrades",
                            os.path.abspath(path)], capture_output=True, text=True)
        if result.returncode in (126, 127):
            raise UpdateError("Installing was cancelled.")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
            raise UpdateError("Installing the update failed" +
                              (f": {detail[0]}" if detail else "."))
        return False  # installed: restart to use it


class WindowsSetupInstaller:
    """For the copy installed by the setup wizard (it has an uninstaller next to it)."""

    def __init__(self, executable: str | None = None, launcher: Callable = subprocess.Popen):
        self._executable = Path(executable or sys.executable)
        self._launch = launcher

    def supported(self) -> bool:
        return getattr(sys, "frozen", False) and any(self._executable.parent.glob("unins*.exe"))

    def pick(self, assets):
        return next((a for a in assets if a.name.endswith("-windows-x64-setup.exe")), None)

    def install(self, path: str) -> bool:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            self._launch([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                          "/CLOSEAPPLICATIONS"], creationflags=flags, close_fds=True)
        except OSError as e:
            raise UpdateError("Couldn't start the installer.") from e
        return True  # setup takes over: quit so it can replace the files


class NoInstaller:
    """Running from source or a portable build: point at the download page instead."""

    def supported(self) -> bool:
        return False

    def pick(self, assets):
        return None

    def install(self, path: str) -> bool:
        raise UpdateError("This copy of Missive can't update itself.")


def platform_installer():
    if sys.platform == "win32":
        return WindowsSetupInstaller()
    if sys.platform.startswith("linux"):
        return DebInstaller()
    return NoInstaller()
