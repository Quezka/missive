"""Moved to the suite's shared toolkit (quezka_ui.fit); this name keeps the app's imports working."""
import sys

from quezka_ui import fit as _shared

sys.modules[__name__] = _shared
