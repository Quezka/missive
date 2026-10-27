"""Wrap a PyInstaller folder build of Missive into an installable .deb.

Layout inside the package:
    /opt/missive/                      the frozen app (binary + bundled Qt/Python)
    /usr/bin/missive                   symlink to /opt/missive/Missive
    /usr/share/applications/<APP_ID>.desktop
    /usr/share/metainfo/<APP_ID>.metainfo.xml   developer/publisher info for app stores
    /usr/share/icons/hicolor/...        scalable SVG + 256px PNG named <APP_ID>

The desktop database and icon cache refresh through dpkg triggers, so no
maintainer scripts are needed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import missive  # noqa: E402  (release metadata only; no Qt imports)

PACKAGING = ROOT / "packaging"

# Bundled Qt still links against these system libraries.
DEPENDS = [
    "libc6",
    "libegl1",
    "libgl1",
    "libfontconfig1",
    "libfreetype6",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
    "libxcb-cursor0",
    "libdbus-1-3",
    "libglib2.0-0t64 | libglib2.0-0",
]


def _architecture() -> str:
    return subprocess.run(["dpkg", "--print-architecture"], check=True,
                          capture_output=True, text=True).stdout.strip()


def _installed_size_kib(root: Path) -> int:
    total = sum(p.lstat().st_size for p in root.rglob("*") if not p.is_dir())
    return (total + 1023) // 1024


def build_deb(app_dir: Path, png_icon: Path, out_dir: Path, work_dir: Path) -> Path:
    if shutil.which("dpkg-deb") is None:
        raise SystemExit("dpkg-deb not found; build the .deb on a Debian/Ubuntu system")
    version, arch, app_id = missive.__version__, _architecture(), missive.APP_ID
    stage = work_dir / "deb-root"
    shutil.rmtree(stage, ignore_errors=True)

    opt = stage / "opt" / "missive"
    shutil.copytree(app_dir, opt, symlinks=True)

    bin_dir = stage / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    os.symlink("/opt/missive/Missive", bin_dir / "missive")

    share = stage / "usr" / "share"
    for folder, name in [("applications", f"{app_id}.desktop"),
                         ("metainfo", f"{app_id}.metainfo.xml")]:
        (share / folder).mkdir(parents=True)
        shutil.copy(PACKAGING / name, share / folder / name)
    doc = share / "doc" / "missive"
    doc.mkdir(parents=True)
    year = __import__("datetime").date.today().year
    (doc / "copyright").write_text(
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
        f"Upstream-Name: Missive\nSource: {missive.HOMEPAGE}\n\n"
        f"Files: *\nCopyright: {year} {missive.DEVELOPER} <{missive.MAINTAINER_EMAIL}>\n"
        "License: GPL-3.0-or-later\n"
        " On Debian systems, the full text of the GNU General Public License version 3\n"
        " can be found in /usr/share/common-licenses/GPL-3.\n")
    icons = share / "icons" / "hicolor"
    (icons / "scalable" / "apps").mkdir(parents=True)
    shutil.copy(ROOT / "missive" / "assets" / "icon.svg", icons / "scalable" / "apps" / f"{app_id}.svg")
    (icons / "256x256" / "apps").mkdir(parents=True)
    shutil.copy(png_icon, icons / "256x256" / "apps" / f"{app_id}.png")

    for path in stage.rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir() or os.access(path, os.X_OK):
            path.chmod(0o755)
        else:
            path.chmod(0o644)

    debian = stage / "DEBIAN"
    debian.mkdir()
    (debian / "control").write_text(
        f"Package: missive\n"
        f"Version: {version}\n"
        f"Architecture: {arch}\n"
        f"Maintainer: {missive.DEVELOPER} <{missive.MAINTAINER_EMAIL}>\n"
        f"Installed-Size: {_installed_size_kib(stage)}\n"
        f"Depends: {', '.join(DEPENDS)}\n"
        f"Section: mail\n"
        f"Priority: optional\n"
        f"Homepage: {missive.HOMEPAGE}\n"
        f"Description: A calm, private mail client\n"
        f" Missive reads your mail over IMAP without changing it and sends only what you\n"
        f" write: threads, search, a safe view of HTML mail with remote pictures blocked.\n"
    )
    debian.chmod(0o755)
    (debian / "control").chmod(0o644)

    out_dir.mkdir(parents=True, exist_ok=True)
    deb = out_dir / f"missive_{version}_{arch}.deb"
    subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(stage), str(deb)],
                   check=True)
    return deb
