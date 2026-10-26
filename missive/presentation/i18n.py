"""Moved to the suite's shared toolkit (quezka_ui.i18n); this name keeps the app's imports working.
The catalogues stay here, in `locales/`."""
import sys

from quezka_ui import i18n as _shared

_shared.configure("missive.presentation.locales")
sys.modules[__name__] = _shared
