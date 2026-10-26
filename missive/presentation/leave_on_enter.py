"""Moved to the suite's shared toolkit (quezka_ui.leave_on_enter); this name keeps the app's imports working."""
import sys

from quezka_ui import leave_on_enter as _shared

sys.modules[__name__] = _shared
