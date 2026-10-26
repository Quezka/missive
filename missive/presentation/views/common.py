"""Moved to the suite's shared toolkit (quezka_ui.widgets); this name keeps the app's imports working."""
import sys

from quezka_ui import widgets as _shared

sys.modules[__name__] = _shared
