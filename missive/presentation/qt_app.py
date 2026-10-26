"""Starts the Qt event loop around an already-wired set of services."""
from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_ID
from . import i18n, leave_on_enter, theme, uiscale
from .icons import APP_ICON


def create_application(argv: list[str]) -> QApplication:
    QApplication.setApplicationName("Missive")
    QApplication.setOrganizationName("Missive")
    QApplication.setDesktopFileName(APP_ID)
    if QApplication.instance() is None:
        uiscale.apply_before_app()  # Qt reads the scale factor once, as the app is created
    app = QApplication.instance() or QApplication(argv)
    app.setStyle("Fusion")
    leave_on_enter.install(app)  # Enter in a one-line box lets go of it
    app.setWindowIcon(QIcon(str(APP_ICON)))
    i18n.install(app=app)  # before any window is built: texts are translated as they're made
    theme.install(app)
    return app


def run(services, argv: list[str]) -> int:
    from .main_window import MainWindow

    app = create_application(argv)
    window = MainWindow(services)
    window.show()
    return app.exec()
