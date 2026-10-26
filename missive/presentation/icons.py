"""The suite's icons (quezka_ui.icons). This module points the shared one at this app's own icon, and
looks everything else up there, so `icons.svg`, `icons.APP_ICON` and the rest keep working."""
from pathlib import Path

from quezka_ui import icons as _shared

APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"
_shared.configure(APP_ICON, "missive")


def __getattr__(name):
    return getattr(_shared, name)
