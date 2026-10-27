"""Build a standalone Missive app for the current platform.

    python scripts/build.py            # folder build in dist/Missive/
    python scripts/build.py --onefile  # single executable
    python scripts/build.py --deb      # Debian/Ubuntu package in dist/
    python scripts/build.py --installer  # Windows setup .exe in dist/ (needs Inno Setup 6)

Run it on Linux to get a Linux build and on Windows to get a Windows .exe;
PyInstaller does not cross-compile.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import missive  # noqa: E402  (release metadata only; no Qt imports)

ASSETS = ROOT / "missive" / "assets"
BUILD = ROOT / "build"


def render_icons() -> Path:
    """Rasterise the SVG icon into the format this platform's executable wants."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (keeps Qt alive)
    renderer = QSvgRenderer(str(ASSETS / "icon.svg"))
    image = QImage(256, 256, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    BUILD.mkdir(exist_ok=True)
    target = BUILD / ("missive.ico" if sys.platform == "win32" else "missive.png")
    if not image.save(str(target)):
        raise SystemExit(f"could not write {target}")
    return target


def write_windows_version_file() -> Path:
    """File properties shown in Windows Explorer (Details tab) for Missive.exe."""
    parts = [int(p) for p in missive.__version__.split(".")]
    nums = tuple(parts + [0] * (4 - len(parts)))
    strings = {
        "CompanyName": missive.DEVELOPER,
        "FileDescription": f"{missive.APP_NAME}: a calm, private mail client",
        "FileVersion": missive.__version__,
        "InternalName": missive.APP_NAME,
        "LegalCopyright": f"Copyright (c) {date.today().year} {missive.DEVELOPER}",
        "OriginalFilename": f"{missive.APP_NAME}.exe",
        "ProductName": missive.APP_NAME,
        "ProductVersion": missive.__version__,
    }
    entries = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    BUILD.mkdir(exist_ok=True)
    target = BUILD / "windows-version.txt"
    target.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {entries}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
""", encoding="utf-8")
    return target


def find_iscc() -> str:
    """Inno Setup's command-line compiler."""
    candidates = [shutil.which("iscc")] + [
        str(Path(base) / "Inno Setup 6" / "ISCC.exe")
        for base in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "") + r"\Programs")
    ]
    found = next((c for c in candidates if c and Path(c).is_file()), None)
    if not found:
        raise SystemExit("Inno Setup 6 not found: install it (choco install innosetup) "
                         "or put ISCC.exe on PATH")
    return found


def build_installer(icon: Path) -> Path:
    """Wrap the folder build in dist/Missive into a Windows setup wizard."""
    out = ROOT / "dist"
    subprocess.run([
        find_iscc(), "/Qp",
        f"/DAppVersion={missive.__version__}",
        f"/DPublisher={missive.DEVELOPER}",
        f"/DHomepage={missive.HOMEPAGE}",
        f"/DSourceDir={out / 'Missive'}",
        f"/DIconFile={icon}",
        f"/DOutputDir={out}",
        str(ROOT / "packaging" / "missive.iss"),
    ], check=True)
    return out / f"Missive-{missive.__version__}-windows-x64-setup.exe"


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--onefile", action="store_true", help="single self-contained executable")
    mode.add_argument("--deb", action="store_true", help="installable .deb (Linux only)")
    mode.add_argument("--installer", action="store_true",
                      help="setup wizard .exe (Windows only, needs Inno Setup 6)")
    mode.add_argument("--installer-only", action="store_true",
                      help="wrap an existing dist/Missive (e.g. after signing it) in the setup")
    args = parser.parse_args()
    if args.deb and not sys.platform.startswith("linux"):
        parser.error("--deb can only be built on Linux")
    if (args.installer or args.installer_only) and sys.platform != "win32":
        parser.error("--installer can only be built on Windows")
    if args.installer_only:
        print(f"Installer: {build_installer(render_icons())}")
        return

    import PyInstaller.__main__

    icon = render_icons()
    windows_only = (["--version-file", str(write_windows_version_file())]
                    if sys.platform == "win32" else [])
    PyInstaller.__main__.run([
        *windows_only,
        str(ROOT / "scripts" / "launcher.py"),
        "--name", "Missive",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--noupx",  # UPX-packed executables are a classic antivirus false positive
        "--onefile" if args.onefile else "--onedir",
        "--icon", str(icon),
        "--add-data", f"{ASSETS}{os.pathsep}missive/assets",
        "--paths", str(ROOT),
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        # Translations are imported by name at run time, so PyInstaller can't see them.
        "--collect-submodules", "missive.presentation.locales",
        # keyring finds its OS backends through entry points; bundle them explicitly.
        "--collect-submodules", "keyring.backends",
        "--copy-metadata", "keyring",
        # Trim Qt modules Missive never uses.
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "tkinter",
    ])
    if args.deb:
        from deb import build_deb

        deb = build_deb(ROOT / "dist" / "Missive", icon, ROOT / "dist", BUILD)
        print(f"\nPackage: {deb}\nInstall with: sudo apt install {deb}")
    elif args.installer:
        print(f"\nInstaller: {build_installer(icon)}")
    else:
        print(f"\nBuilt into {ROOT / 'dist'}")


if __name__ == "__main__":
    main()
