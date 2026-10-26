"""Line icons drawn from inline SVG, tinted at runtime to match the theme.

Paths adapted from Feather Icons (MIT licence, https://feathericons.com).
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"

_PATHS = {
    "today": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41'
             'M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
    "week": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "coursework": '<path d="M9 11l3 3L22 4"/>'
                  '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "notes": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
             '<path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
    "school": '<path d="M22 10L12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "chevron-left": '<path d="M15 18l-6-6 6-6"/>',
    "chevron-right": '<path d="M9 18l6-6-6-6"/>',
    "chevron-down": '<path d="M6 9l6 6 6-6"/>',
    "chevron-up": '<path d="M18 15l-6-6-6 6"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "search": '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>',
    "trash": '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6'
             'M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "pin": '<path d="M12 17v5M9 10.76V6h6v4.76l2 3.24H7z"/><path d="M8 2h8"/>',
    "more": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
            '<circle cx="5" cy="12" r="1"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06'
                'a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21'
                'a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06'
                'a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3'
                'a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06'
                'a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3'
                'a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06'
                'a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21'
                'a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "calendar-day": '<rect x="3" y="4" width="18" height="18" rx="2"/>'
                    '<path d="M16 2v4M8 2v4M3 10h18"/><rect x="8" y="14" width="4" height="4" rx="1"/>',
    "star": '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14'
            ' 2 9.27l6.91-1.01L12 2z"/>',
    "layers": '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/>'
              '<path d="M2 12l10 5 10-5"/>',
    "tag": '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59'
           'a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5"/>',
    "briefcase": '<rect x="2" y="7" width="20" height="14" rx="2"/>'
                 '<path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "zoom-in": '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M11 8v6M8 11h6"/>',
    "zoom-out": '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M8 11h6"/>',
    "fit-day": '<path d="M7 15l5 5 5-5M7 9l5-5 5 5"/><path d="M4 12h16"/>',
    "timer": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M9 2h6M12 2v3"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "pause": '<path d="M8 4v16M16 4v16"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/><path d="M3 3v5h5"/>',
    "skip": '<path d="M5 4l10 8-10 8zM19 5v14"/>',
    "bold": '<path d="M6 4h8a4 4 0 0 1 0 8H6zM6 12h9a4 4 0 0 1 0 8H6z"/>',
    "italic": '<path d="M19 4h-9M14 20H5M15 4L9 20"/>',
    "heading": '<path d="M6 4v16M18 4v16M6 12h12"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "checklist": '<path d="M3 5l2 2 4-4M3 15l2 2 4-4M13 6h8M13 16h8"/>',
    "code": '<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>',
    "quote": '<path d="M3 21c3 0 7-1 7-8V5H3v7h4M14 21c3 0 7-1 7-8V5h-7v7h4"/>',
    "pointer": '<path d="M4 3l7 17 2.5-7.5L21 10z"/><path d="M13.5 12.5L20 19"/>',
    "entity": '<rect x="3" y="6" width="18" height="12" rx="2"/>',
    "relationship": '<path d="M12 3l9 9-9 9-9-9z"/>',
    "attribute": '<circle cx="12" cy="7" r="3"/><path d="M12 10v11"/>',
    "class": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M4 9h16M4 15h16"/>',
    "link": '<path d="M5 19L19 5"/><path d="M11 5h8v8"/>',
    "inherit": '<path d="M12 21V9"/><path d="M6 10l6-7 6 7z"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>'
            '<path d="M17 21v-8H7v8M7 3v5h8"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9'
              'a2 2 0 0 1 2 2z"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>'
             '<path d="M21 15l-5-5L5 21"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
                '<path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>',
    "diagram": '<rect x="2" y="3" width="8" height="6" rx="1"/><rect x="14" y="15" width="8" height="6"'
               ' rx="1"/><path d="M6 9v4a2 2 0 0 0 2 2h6"/>',
    "fit": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3'
           'M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "swap": '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/>'
            '<path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    "align": '<path d="M4 3v18M8 7h12M8 13h8M8 17h10"/>',
    "side-panel": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M15 3v18"/>',
    "x": '<path d="M18 6L6 18M6 6l12 12"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M16 7l3 3M18 5l2 2"/>',
    "bell": '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>'
            '<path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
}


def svg(name: str, color: str, stroke: float = 2.0) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{_PATHS[name]}</svg>')


def pixmap(name: str, color: str, size: int = 18, stroke: float = 2.0) -> QPixmap:
    app = QGuiApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, color, stroke).encode()))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pm.width(), pm.height()))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, checked_color: str | None = None, size: int = 18,
         disabled_color: str | None = None) -> QIcon:
    result = QIcon(pixmap(name, color, size))
    if checked_color:
        result.addPixmap(pixmap(name, checked_color, size), QIcon.Normal, QIcon.On)
    if disabled_color:
        for state in (QIcon.Off, QIcon.On):
            result.addPixmap(pixmap(name, disabled_color, size), QIcon.Disabled, state)
    return result


_CACHE = Path(tempfile.gettempdir()) / "missive-icons"


def icon_file(name: str, color: str, stroke: float = 2.0) -> str:
    """An SVG file on disk, for style sheets that need url(...) images."""
    data = svg(name, color, stroke)
    _CACHE.mkdir(exist_ok=True)
    path = _CACHE / f"{name}-{hashlib.sha1(data.encode()).hexdigest()[:10]}.svg"
    if not path.exists():
        path.write_text(data, encoding="utf-8")
    return path.as_posix()
