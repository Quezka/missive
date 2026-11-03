"""Updating from GitHub releases: the use case with fakes, the adapters with canned answers."""
import hashlib
import io
import json
import subprocess
import urllib.error
from datetime import timedelta

import pytest

from missive.application.updates import UpdateService
from missive.infrastructure.settings import MemorySettings

from .update_fakes import FakeInstaller, FakeReleases

from missive.application.errors import UpdateError
from missive.application.ports import ReleaseAsset, ReleaseInfo
from missive.application.updates import parse_version
from missive.infrastructure.updates import (
    DebInstaller, GitHubReleaseFeed, NoInstaller, WindowsSetupInstaller, deb_architecture,
)

DEB = ReleaseAsset(f"missive_9.0.0_{deb_architecture()}.deb", "https://x/missive.deb", 10, None)
EXE = ReleaseAsset("Missive-9.0.0-windows-x64-setup.exe", "https://x/setup.exe", 10, None)


def release(version="9.0.0"):
    return ReleaseInfo(version, "## New\n- Things", "https://github.com/Quezka/missive/releases",
                       (DEB, EXE))


class Clock:
    def __init__(self):
        from datetime import datetime
        self.now = datetime(2026, 9, 30, 10, 0)

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def releases():
    return FakeReleases()


@pytest.fixture
def installer():
    return FakeInstaller()


@pytest.fixture
def services(releases, installer, clock):
    class Services:
        updates = UpdateService(releases, installer, MemorySettings(), "0.2.0", clock)
    return Services()


# ---- use case -------------------------------------------------------------------------

def test_versions_compare_as_numbers():
    assert parse_version("v0.10.0") > parse_version("0.9.9")
    assert parse_version("1.0.0") > parse_version("0.99.0")
    assert parse_version("0.11.0") == (0, 11, 0)
    assert parse_version("nonsense") < parse_version("0.0.1")


def test_a_newer_release_is_offered_with_the_right_file(services, releases):
    releases.release = release()
    update = services.updates.check()
    assert update.version == "9.0.0" and update.asset == DEB and update.can_install
    assert update.current == services.updates.current_version


def test_nothing_is_offered_when_up_to_date(services, releases):
    assert services.updates.check() is None  # no release at all
    releases.release = release(services.updates.current_version)
    assert services.updates.check() is None
    releases.release = release("0.0.1")
    assert services.updates.check() is None


def test_a_copy_that_cant_install_gets_the_download_page(services, releases, installer):
    installer._supported = False
    releases.release = release()
    update = services.updates.check()
    assert not update.can_install and update.page_url.endswith("/releases")


def test_download_and_install(services, releases, installer):
    releases.release = release()
    update = services.updates.check()
    seen = []
    path = services.updates.download(update, lambda done, total: seen.append((done, total)))
    assert seen[-1] == (10, 10)
    assert services.updates.install(path) is False and installer.installed == [path]


def test_daily_check_skip_and_switch_off(services, clock):
    updates = services.updates
    assert updates.due()
    updates.mark_checked()
    assert not updates.due()
    clock.now += timedelta(hours=21)
    assert updates.due()
    updates.set_auto_check(False)
    assert not updates.due() and not updates.auto_check()
    updates.skip("9.0.0")
    assert updates.skipped("9.0.0") and not updates.skipped("9.0.1")


# ---- GitHub feed ------------------------------------------------------------------------

class Opener:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(answer if isinstance(answer, bytes) else json.dumps(answer).encode())


GITHUB = {
    "tag_name": "v0.12.0", "body": "Notes", "html_url": "https://github.com/Quezka/missive/releases/tag/v0.12.0",
    "draft": False, "prerelease": False,
    "assets": [{"name": "missive_0.12.0_amd64.deb", "browser_download_url": "https://dl/deb",
                "size": 5, "digest": "sha256:" + hashlib.sha256(b"hello").hexdigest()},
               {"name": "Missive-0.12.0-windows-x64-setup.exe", "browser_download_url": "https://dl/exe",
                "size": 7}],
}


def test_latest_release_is_read_from_github():
    opener = Opener(GITHUB)
    info = GitHubReleaseFeed("Quezka/missive", "0.11.0", opener).latest()
    assert info.version == "0.12.0" and info.notes == "Notes"
    assert info.assets[0].sha256 == hashlib.sha256(b"hello").hexdigest()
    assert info.assets[1].sha256 is None
    request = opener.requests[0]
    assert request.full_url == "https://api.github.com/repos/Quezka/missive/releases/latest"
    assert request.headers["User-agent"] == "Missive/0.11.0"


def test_no_release_or_private_repo_means_no_update():
    not_found = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b"{}"))
    assert GitHubReleaseFeed("Quezka/missive", "0.11.0", Opener(not_found)).latest() is None


def test_rate_limits_and_offline_are_explained():
    limited = urllib.error.HTTPError("u", 403, "rate limited", {}, io.BytesIO(b"{}"))
    with pytest.raises(UpdateError, match="limiting"):
        GitHubReleaseFeed("r/r", "1", Opener(limited)).latest()
    with pytest.raises(UpdateError, match="internet"):
        GitHubReleaseFeed("r/r", "1", Opener(urllib.error.URLError("x"))).latest()


def test_download_checks_size_and_checksum(tmp_path):
    good = ReleaseAsset("missive.deb", "https://dl/deb", 5, hashlib.sha256(b"hello").hexdigest())
    feed = GitHubReleaseFeed("r/r", "1", Opener(b"hello"), folder=tmp_path)
    seen = []
    path = feed.download(good, lambda done, total: seen.append((done, total)))
    assert open(path, "rb").read() == b"hello" and seen[-1] == (5, 5)

    tampered = GitHubReleaseFeed("r/r", "1", Opener(b"hellO"), folder=tmp_path)
    with pytest.raises(UpdateError, match="damaged"):
        tampered.download(good, lambda *a: None)
    short = GitHubReleaseFeed("r/r", "1", Opener(b"hel"), folder=tmp_path)
    with pytest.raises(UpdateError, match="damaged"):
        short.download(ReleaseAsset("missive.deb", "https://dl/deb", 5), lambda *a: None)
    assert list(tmp_path.glob("*.part")) == []


# ---- installers ---------------------------------------------------------------------------

def test_deb_installer_picks_this_architecture_and_uses_pkexec(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    installer = DebInstaller("/opt/missive/Missive", runner)
    assert installer.pick((EXE, DEB)) == DEB
    assert installer.install(str(tmp_path / "q.deb")) is False
    assert calls[0][:4] == ["pkexec", "apt-get", "install", "-y"]
    assert calls[0][-1] == str(tmp_path / "q.deb")


def test_deb_installer_reports_cancel_and_failure():
    cancelled = DebInstaller("/opt/missive/Missive",
                             lambda c, **k: subprocess.CompletedProcess(c, 126, "", ""))
    with pytest.raises(UpdateError, match="cancelled"):
        cancelled.install("/tmp/q.deb")
    broken = DebInstaller("/opt/missive/Missive", lambda c, **k: subprocess.CompletedProcess(
        c, 100, "", "E: Broken packages"))
    with pytest.raises(UpdateError, match="Broken packages"):
        broken.install("/tmp/q.deb")


def test_running_from_source_cant_self_update():
    assert not DebInstaller("/usr/bin/python3").supported()  # not frozen, not in /opt/missive
    assert not NoInstaller().supported() and NoInstaller().pick((DEB,)) is None


def test_windows_installer_runs_the_setup_silently(tmp_path):
    launched = []
    installer = WindowsSetupInstaller(str(tmp_path / "Missive.exe"),
                                      lambda command, **kwargs: launched.append(command))
    assert installer.pick((DEB, EXE)) == EXE
    assert installer.install("C:/setup.exe") is True  # setup takes over; Missive quits
    assert launched[0][0] == "C:/setup.exe" and "/SILENT" in launched[0]
    assert not installer.supported()  # not frozen and no uninstaller next to it
