"""Translations for the user interface.

Wrap on-screen text in `_()`; it returns the text in the chosen language, or the
English original when there's no translation. Text with values in it uses named
placeholders: `_("Delete “{title}”?").format(title=...)`.

The language is picked once at start-up (changing it asks for a restart).
Catalogues live in `locales/<code>.py`; tests check every `_()` string has a
Russian and an Italian translation.
"""
from __future__ import annotations

import importlib
from datetime import date

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator

# (code, name in its own language). "" follows the system.
LANGUAGES = [("", "System"), ("en", "English"), ("it", "Italiano"), ("ru", "Русский")]
SUPPORTED = {"en", "it", "ru"}
_QT_LOCALES = {"en": QLocale.English, "it": QLocale.Italian, "ru": QLocale.Russian}

_language = "en"
_messages: dict[str, str] = {}
_plurals: dict[str, tuple[str, str, str]] = {}
_names: dict[str, list[str]] = {}
_qt_translators: list[QTranslator] = []

EN_NAMES = {
    "weekdays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "weekdays_short": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "months": ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"],
    "months_short": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                     "Nov", "Dec"],
}


def chosen_language() -> str:
    """The Settings choice: "", "en", "it" or "ru"."""
    return str(QSettings().value("language", ""))


def set_chosen_language(code: str):
    QSettings().setValue("language", code)


def resolve(code: str) -> str:
    """What "" (system) means here: Italian and Russian systems get their language, the rest English."""
    if code in SUPPORTED:
        return code
    system = QLocale.system().language()
    return next((c for c, qt in _QT_LOCALES.items() if qt == system), "en")


def install(code: str | None = None, app=None) -> str:
    """Activate a language; with an app, also Qt's own texts (buttons, dialogs)."""
    global _language, _messages, _plurals, _names
    _language = resolve(chosen_language() if code is None else code)
    if _language == "en":
        _messages, _plurals, _names = {}, {}, {}
    else:
        module = importlib.import_module(f"{__package__}.locales.{_language}")
        _messages, _plurals, _names = module.MESSAGES, module.PLURALS, module.NAMES
    if app is not None:
        for translator in _qt_translators:
            app.removeTranslator(translator)
        _qt_translators.clear()
        if _language != "en":
            folder = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
            translator = QTranslator(app)
            if translator.load(f"qtbase_{_language}", folder):
                app.installTranslator(translator)
                _qt_translators.append(translator)
        QLocale.setDefault(QLocale(_QT_LOCALES[_language]))
    return _language


def language() -> str:
    return _language


def _(text: str) -> str:
    return _messages.get(text, text)


def C_(context: str, text: str) -> str:
    """Like `_()`, for words whose translation depends on use, e.g. C_("button", "Start")."""
    return _messages.get(f"{context}|{text}", _messages.get(text, text))


def N_(text: str) -> str:
    """Marks text for translation where it's defined; `_()` translates it where shown."""
    return text


class Translated(dict):
    """A label table whose values come out translated."""

    def __getitem__(self, key):
        return _(super().__getitem__(key))

    def items(self):
        return [(k, _(v)) for k, v in super().items()]

    def values(self):
        return [_(v) for v in super().values()]


def weekday_names() -> list[str]:
    return [_name("weekdays", i) for i in range(7)]


# ---- plurals ----------------------------------------------------------------------

def plural_form(n: int) -> int:
    """Russian: 1 урок (0), 2-4 урока (1), 5+ уроков (2), with 11-14 counting as 5+."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return 0
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 1
    return 2


def _form(n: int) -> int:
    """Which plural form the active language uses: Italian has two, Russian three."""
    return (0 if n == 1 else 1) if _language == "it" else plural_form(n)


def plural(n: int, word: str, many: str | None = None) -> str:
    """"3 entities" / "3 сущности". `word` is the English singular (the catalogue key),
    `many` the English plural when it isn't just word + "s"."""
    if _language != "en" and word in _plurals:
        return f"{n} {_plurals[word][_form(n)]}"
    return f"{n} {word if n == 1 else (many or word + 's')}"


# ---- names of days and months -----------------------------------------------------

def _name(kind: str, index: int) -> str:
    return (_names.get(kind) or EN_NAMES.get(kind) or EN_NAMES[kind.replace("_genitive", "")])[index]


def weekday_name(d: date) -> str:
    return _name("weekdays", d.weekday())


def weekday_short(d: date) -> str:
    return _name("weekdays_short", d.weekday())


def month_name(d: date) -> str:
    """Standalone, e.g. for "September 2026" / "Сентябрь 2026"."""
    return _name("months", d.month - 1)


def month_of(d: date) -> str:
    """After a day number: "23 September" / "23 сентября"."""
    return _name("months_genitive", d.month - 1)


def month_short(d: date) -> str:
    return _name("months_short", d.month - 1)
