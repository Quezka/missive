"""Design tokens, palette and style sheet. Follows the system light/dark setting."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from . import icons


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    surface: str
    raised: str
    sidebar: str
    border: str
    hover: str
    text: str
    muted: str
    faint: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    danger: str
    success: str


LIGHT = Theme(
    dark=False,
    bg="#f5f6f8", surface="#ffffff", raised="#f0f1f4", sidebar="#eceef2",
    border="#e2e4e9", hover="#e7e9ee",
    text="#16181d", muted="#636a75", faint="#9aa0aa",
    accent="#5b5bd6", accent_hover="#4c4cc4", accent_soft="#e6e6fb", on_accent="#ffffff",
    danger="#e5484d", success="#30a46c",
)

DARK = Theme(
    dark=True,
    bg="#111214", surface="#18191c", raised="#202226", sidebar="#141517",
    border="#2a2c31", hover="#26282d",
    text="#ecedef", muted="#9ba1ab", faint="#6b7079",
    accent="#8182f0", accent_hover="#9394f5", accent_soft="#262747", on_accent="#ffffff",
    danger="#ff6369", success="#3dd68c",
)

RADIUS = 10


MODES = ("system", "light", "dark")


class ThemeManager(QObject):
    """Owns the active theme; follows the system scheme unless the user picked one."""

    changed = Signal(object)  # Theme

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        self.theme = LIGHT
        mode = QSettings().value("appearance", "system")
        self.mode = mode if mode in MODES else "system"
        app.styleHints().colorSchemeChanged.connect(lambda _scheme: self.apply())
        self.apply()

    def set_mode(self, mode: str):
        self.mode = mode
        QSettings().setValue("appearance", mode)
        self.apply()

    def apply(self):
        if self.mode == "system":
            dark = self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark
        else:
            dark = self.mode == "dark"
        self.theme = DARK if dark else LIGHT
        self.app.setPalette(palette(self.theme))
        self.app.setStyleSheet(stylesheet(self.theme))
        self.changed.emit(self.theme)


_manager: ThemeManager | None = None


def install(app: QApplication) -> ThemeManager:
    global _manager
    _manager = ThemeManager(app)
    return _manager


def manager() -> ThemeManager:
    assert _manager is not None, "theme.install() must run before building widgets"
    return _manager


def current() -> Theme:
    return _manager.theme if _manager else LIGHT


def themed(apply) -> None:
    """Call `apply(theme)` now and again whenever the theme changes."""
    apply(current())
    if _manager is not None:
        def safe(theme):
            try:
                apply(theme)
            except RuntimeError:  # the widget was deleted
                pass
        _manager.changed.connect(safe)


def disabled(t: Theme) -> str:
    """Text and icons of things you can't use yet: clearly paler than muted text."""
    return "#4a4e57" if t.dark else "#bcc0c8"


def set_icon(widget, name: str, role: str = "muted", checked_role: str | None = None,
             size: int = 18) -> None:
    """Give a button a line icon that recolours with the theme."""
    def apply(t: Theme):
        widget.setIcon(icons.icon(name, getattr(t, role),
                                  getattr(t, checked_role) if checked_role else None, size,
                                  disabled(t)))
    themed(apply)


def palette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.Window: t.bg, QPalette.WindowText: t.text,
        QPalette.Base: t.surface, QPalette.AlternateBase: t.raised,
        QPalette.Text: t.text, QPalette.PlaceholderText: t.faint,
        QPalette.Button: t.raised, QPalette.ButtonText: t.text,
        QPalette.Highlight: t.accent, QPalette.HighlightedText: t.on_accent,
        QPalette.ToolTipBase: t.raised, QPalette.ToolTipText: t.text,
        QPalette.Link: t.accent, QPalette.Mid: t.border, QPalette.Midlight: t.hover,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(t.faint))
    return p


def stylesheet(t: Theme) -> str:
    check = icons.icon_file("check", t.on_accent, 3)
    chevron = icons.icon_file("chevron-down", t.muted)
    chevron_up = icons.icon_file("chevron-up", t.muted)
    r = RADIUS
    return f"""
    * {{ outline: none; }}
    QMainWindow, QDialog {{ background: {t.bg}; }}
    QToolTip {{ background: {t.raised}; color: {t.text}; border: 1px solid {t.border};
               border-radius: 6px; padding: 4px 8px; }}

    /* ---- sidebar ---- */
    #sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
    #brand {{ font-size: 15pt; font-weight: 700; color: {t.text}; }}
    #sidebarSection {{ color: {t.faint}; font-size: 8.5pt; font-weight: 600;
                       letter-spacing: 1px; padding: 0 12px; }}
    QToolButton#nav {{ background: transparent; border: none; border-radius: 8px;
                       padding: 8px 12px; color: {t.muted}; text-align: left;
                       font-weight: 500; }}
    QToolButton#nav:hover {{ background: {t.hover}; color: {t.text}; }}
    QToolButton#nav:disabled {{ color: {disabled(t)}; background: transparent; }}
    QToolButton#nav:checked {{ background: {t.accent_soft}; color: {t.accent};
                               font-weight: 600; }}

    /* ---- page chrome ---- */
    #page {{ background: {t.bg}; }}
    #pageTitle {{ font-size: 19pt; font-weight: 700; color: {t.text}; }}
    #pageSubtitle {{ color: {t.muted}; }}
    #card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r + 4}px; }}
    #cardTitle {{ font-weight: 700; color: {t.text}; font-size: 10.5pt; }}
    #muted {{ color: {t.muted}; }}
    #hint {{ color: {t.faint}; }}
    QLabel#danger {{ color: {t.danger}; }}
    #stat {{ font-size: 22pt; font-weight: 700; color: {t.text}; }}
    #sheetTitle {{ font-size: 16pt; font-weight: 700; color: {t.text}; }}
    QTextBrowser#sheetBody {{ background: {t.raised}; border: none; border-radius: 10px;
        padding: 10px 12px; }}
    QLabel#chip, QLabel#chipDanger {{ background: {t.raised}; color: {t.text};
        border-radius: 10px; padding: 3px 10px; font-size: 9pt; font-weight: 600; }}
    QLabel#chipDanger {{ background: {t.accent_soft}; color: {t.danger}; }}
    QLineEdit#titleEdit {{ font-size: 14pt; font-weight: 600; padding: 8px 10px; }}
    #tileCaption {{ color: {t.muted}; font-size: 8.5pt; font-weight: 600;
        letter-spacing: 0.5px; }}
    #tileValue {{ font-size: 20pt; font-weight: 700; color: {t.text}; }}
    #segmented {{ background: {t.raised}; border: 1px solid {t.border}; border-radius: 9px; }}
    QPushButton#segment {{ background: transparent; border: none; border-radius: 7px;
        padding: 5px 12px; color: {t.muted}; font-weight: 500; }}
    QPushButton#segment:hover {{ color: {t.text}; }}
    QPushButton#segment:checked {{ background: {t.surface}; color: {t.text};
        font-weight: 600; border: 1px solid {t.border}; }}
    #badge {{ background: {t.accent_soft}; color: {t.accent}; border-radius: 9px;
              padding: 1px 8px; font-weight: 600; font-size: 9pt; }}

    /* ---- buttons ---- */
    QPushButton, QToolButton {{ background: {t.raised}; color: {t.text};
        border: 1px solid {t.border}; border-radius: 8px; padding: 6px 14px; }}
    QPushButton:hover, QToolButton:hover {{ background: {t.hover}; }}
    QPushButton:pressed, QToolButton:pressed {{ background: {t.border}; }}
    QPushButton:disabled, QToolButton:disabled {{ color: {t.faint}; background: transparent; }}
    QPushButton:checked, QToolButton:checked {{ background: {t.accent_soft}; color: {t.accent};
        border-color: {t.accent_soft}; }}
    QPushButton#primary {{ background: {t.accent}; color: {t.on_accent}; border: none;
        font-weight: 600; padding: 7px 16px; }}
    QPushButton#primary:hover {{ background: {t.accent_hover}; }}
    QPushButton#danger {{ color: {t.danger}; }}
    QToolButton#icon, QPushButton#icon {{ background: transparent; border: none;
        border-radius: 8px; padding: 6px; }}
    QToolButton#icon:hover, QPushButton#icon:hover {{ background: {t.hover}; }}
    QToolButton#icon:checked, QPushButton#icon:checked {{ background: {t.accent_soft}; }}
    QToolButton::menu-indicator, QPushButton::menu-indicator {{ image: none; width: 0; }}
    QToolButton#day {{ min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
        padding: 0; border-radius: 13px; border: 1px solid {t.border}; background: {t.surface};
        color: {t.muted}; font-weight: 600; font-size: 9pt; }}
    QToolButton#day:hover {{ border-color: {t.accent}; }}
    QToolButton#day:checked {{ background: {t.accent}; border-color: {t.accent};
        color: {t.on_accent}; }}

    /* ---- the drawing page ---- */
    QToolButton#tool {{ background: transparent; border: none; border-radius: 8px;
        padding: 5px 10px; color: {t.muted}; font-weight: 500; }}
    QToolButton#tool:hover {{ background: {t.hover}; color: {t.text}; }}
    QToolButton#tool:checked {{ background: {t.accent_soft}; color: {t.accent};
        font-weight: 600; }}
    QToolButton#tool[popupMode="1"] {{ padding-right: 22px; }}
    QToolButton#tool::menu-button {{ border: none; width: 18px; }}
    QToolButton#tool::menu-arrow {{ image: url({chevron}); width: 12px; height: 12px; }}
    #rule {{ background: {t.border}; }}
    QGraphicsView {{ border: none; border-bottom-left-radius: {r + 4}px;
        border-bottom-right-radius: {r + 4}px; }}
    QPlainTextEdit#code, QTextBrowser#code {{ background: {t.raised}; border: none;
        border-radius: 10px; padding: 10px 12px; }}
    QListWidget#recent::item {{ padding: 9px 10px; }}
    QToolButton#startTile {{ background: {t.raised}; border: 1px solid {t.border};
        border-radius: 12px; padding: 14px; color: {t.text}; font-weight: 600; }}
    QToolButton#startTile:hover {{ border-color: {t.accent}; background: {t.accent_soft}; }}

    /* ---- inputs ---- */
    QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox {{
        background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 8px; padding: 6px 10px; selection-background-color: {t.accent};
        selection-color: {t.on_accent}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
    QDateEdit:focus, QTimeEdit:focus, QSpinBox:focus {{
        border: 1px solid {t.accent}; }}
    QLineEdit#search {{ background: {t.raised}; border-color: transparent; }}
    QLineEdit#search:focus {{ background: {t.surface}; border-color: {t.accent}; }}
    QPlainTextEdit#bare, QTextBrowser#bare {{ border: none; background: transparent;
        padding: 4px 2px; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({chevron}); width: 14px;
        height: 14px; }}
    QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: none; }}
    QSpinBox {{ padding-right: 24px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 22px;
        border: none; background: transparent; }}
    QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 3px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 3px; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t.hover};
        border-radius: 4px; }}
    QSpinBox::up-arrow {{ image: url({chevron_up}); width: 11px; height: 11px; }}
    QSpinBox::down-arrow {{ image: url({chevron}); width: 11px; height: 11px; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border};
        border-radius: 8px; padding: 4px; selection-background-color: {t.accent_soft};
        selection-color: {t.text}; }}

    QCheckBox {{ spacing: 8px; color: {t.text}; }}
    QCheckBox::indicator, QListWidget::indicator, QTreeWidget::indicator {{
        width: 16px; height: 16px; border-radius: 5px; border: 1.5px solid {t.faint};
        background: {t.surface}; }}
    QCheckBox::indicator:hover, QListWidget::indicator:hover, QTreeWidget::indicator:hover {{
        border-color: {t.accent}; }}
    QCheckBox::indicator:checked, QListWidget::indicator:checked,
    QTreeWidget::indicator:checked {{ background: {t.accent}; border-color: {t.accent};
        image: url({check}); }}

    /* ---- lists ---- */
    QListWidget, QTreeWidget, QTableWidget {{ background: transparent; border: none;
        color: {t.text}; }}
    QListWidget::item, QTreeWidget::item {{ padding: 7px 8px; border-radius: 8px;
        margin: 1px 0; }}
    QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t.hover}; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: {t.accent_soft};
        color: {t.text}; }}
    QTreeWidget::branch {{ background: transparent; }}
    QHeaderView::section {{ background: transparent; color: {t.faint}; border: none;
        border-bottom: 1px solid {t.border}; padding: 6px 8px; font-weight: 600;
        font-size: 9pt; }}
    QTableWidget {{ gridline-color: {t.border}; }}

    /* ---- scrollbars ---- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {t.border}; border-radius: 3px; min-height: 30px;
        min-width: 30px; }}
    QScrollBar::handle:hover {{ background: {t.faint}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    /* ---- menus, splitters ---- */
    QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 6px;
        border-radius: 10px; }}
    QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 6px; color: {t.text}; }}
    QMenu::item:selected {{ background: {t.hover}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}
    QSplitter::handle {{ background: transparent; }}
    QCalendarWidget QWidget {{ alternate-background-color: {t.raised}; }}
    QCalendarWidget QToolButton {{ border: none; background: transparent; }}
    """
