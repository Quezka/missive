"""Building blocks shared by the pages: header, cards, buttons, segmented controls."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import theme


class Page(QWidget):
    """A top-level page: padded, themed background, header row on top."""

    def __init__(self, parent=None, margins=(28, 22, 28, 24)):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(*margins)
        self.root.setSpacing(16)
        self.title = QLabel(objectName="pageTitle")
        self.subtitle = QLabel(objectName="pageSubtitle")
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.header.addLayout(titles)
        self.header.addStretch()
        self.root.addLayout(self.header)

    def add_actions(self, *widgets):
        for w in widgets:
            self.header.addWidget(w, 0, Qt.AlignVCenter)


class Card(QFrame):
    """Rounded surface with an optional title row."""

    def __init__(self, title: str | None = None, padding: int = 16, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(10)
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(8)
        if title:
            self.title_label = QLabel(title, objectName="cardTitle")
            self.title_row.addWidget(self.title_label)
            self.title_row.addStretch()
            self.body.addLayout(self.title_row)

    def add(self, widget, stretch: int = 0):
        self.body.addWidget(widget, stretch)
        return widget


class Segmented(QFrame):
    """A few mutually exclusive choices side by side (instead of tabs)."""

    changed = Signal(object)  # the chosen value

    def __init__(self, options: list[tuple[object, str]], parent=None):
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.values = []
        for i, (value, text) in enumerate(options):
            b = QPushButton(text, objectName="segment", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            # Room for the text in bold (as it is when chosen), so choosing doesn't clip it.
            bold = QFont(b.font())
            bold.setBold(True)
            b.setMinimumWidth(QFontMetrics(bold).horizontalAdvance(text) + 30)
            self.group.addButton(b, i)
            self.values.append(value)
            row.addWidget(b)
        self.group.idClicked.connect(lambda i: self.changed.emit(self.values[i]))

    def set_value(self, value):
        if value in self.values:
            self.group.button(self.values.index(value)).setChecked(True)

    def value(self):
        return self.values[self.group.checkedId()] if self.group.checkedId() >= 0 else None


def icon_button(name: str, tooltip: str, checkable: bool = False,
                checked_role: str | None = "accent") -> QToolButton:
    button = QToolButton(objectName="icon", toolTip=tooltip, checkable=checkable)
    button.setCursor(Qt.PointingHandCursor)
    theme.set_icon(button, name, "muted", checked_role if checkable else None)
    return button


def primary_button(text: str, icon_name: str | None = "plus") -> QPushButton:
    result = QPushButton(text, objectName="primary")
    result.setCursor(Qt.PointingHandCursor)
    if icon_name:
        theme.set_icon(result, icon_name, "on_accent", size=16)
    return result


def button(text: str, icon_name: str | None = None) -> QPushButton:
    result = QPushButton(text)
    result.setCursor(Qt.PointingHandCursor)
    if icon_name:
        theme.set_icon(result, icon_name, "muted", size=16)
    return result


def label(text: str = "", role: str = "muted") -> QLabel:
    return QLabel(text, objectName=role)


def caption(text: str) -> QLabel:
    return QLabel(text.upper(), objectName="tileCaption")
