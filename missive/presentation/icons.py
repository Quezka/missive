"""The suite's icons (quezka_ui.icons). This module points the shared one at this app's own icon, and
looks everything else up there, so `icons.svg`, `icons.APP_ICON` and the rest keep working."""
from pathlib import Path

from quezka_ui import icons as _shared

APP_ICON = Path(__file__).resolve().parent.parent / "assets" / "icon.svg"
_shared.configure(APP_ICON, "missive")


def __getattr__(name):
    return getattr(_shared, name)

# Icons the mail folders and the reader need; the shared set has none of these (Feather Icons, MIT).
_shared.register({
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
             '<path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "send": '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
    "archive": '<polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/>'
               '<line x1="10" y1="12" x2="14" y2="12"/>',
    "alert": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
             '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "mail": '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>'
            '<polyline points="22,6 12,13 2,6"/>',
    "paperclip": '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
})
