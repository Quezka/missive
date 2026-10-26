import os

import pytest

from missive.presentation import uiscale


def test_automatic_scale_depends_on_the_screen():
    assert uiscale.factor("auto", 768) == 0.85
    assert uiscale.factor("auto", 800) == 0.85
    assert uiscale.factor("auto", 1080) == 1.0
    assert uiscale.factor("auto", None) == 1.0
    assert uiscale.factor("115", 768) == 1.15 and uiscale.factor("80", 2160) == 0.8
    assert uiscale.factor("nonsense", 768) == 1.0


def test_the_choice_is_remembered_and_junk_is_ignored(monkeypatch):
    from PySide6.QtCore import QSettings
    store = {}
    monkeypatch.setattr(QSettings, "value", lambda self, key, default=None: store.get(key, default))
    monkeypatch.setattr(QSettings, "setValue", lambda self, key, value: store.__setitem__(key, value))
    assert uiscale.chosen() == "auto"
    uiscale.set_chosen("115")
    assert uiscale.chosen() == "115"
    store["ui_scale"] = "7"
    assert uiscale.chosen() == "auto"


def test_the_scale_is_handed_to_qt_unless_already_set(monkeypatch):
    monkeypatch.setattr(uiscale, "chosen", lambda: "130")
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    uiscale.apply_before_app()
    assert os.environ["QT_SCALE_FACTOR"] == "1.3"
    monkeypatch.setenv("QT_SCALE_FACTOR", "2")
    uiscale.apply_before_app()
    assert os.environ["QT_SCALE_FACTOR"] == "2"


def test_a_100_percent_choice_leaves_qt_alone(monkeypatch):
    monkeypatch.setattr(uiscale, "chosen", lambda: "100")
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    uiscale.apply_before_app()
    assert "QT_SCALE_FACTOR" not in os.environ
    monkeypatch.undo()


@pytest.mark.parametrize("height", [768, 1080])
def test_windows_and_dialogs_stay_inside_the_screen(height, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

    from missive.presentation import fit
    from missive.presentation.qt_app import create_application
    create_application(["t"])
    monkeypatch.setattr(fit, "available", lambda widget=None: QRect(0, 0, 1366, height - 40))
    window = QWidget()
    fit.clamp_window(window, 1400, 900, 1020, 660)
    assert window.width() <= 1366 and window.height() <= height - 40 - fit.MARGIN
    dialog = QDialog()
    column = QVBoxLayout(dialog)
    for i in range(60):
        column.addWidget(QLabel(f"row {i}"))
    fit.scrollable(dialog)
    assert dialog.height() <= int((height - 40) * 0.9)


def test_the_screen_probe_keeps_the_app_names():
    """The desktop file name groups a window with its dock icon; the probe used to wipe it."""
    import subprocess
    import sys
    code = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("QT_SCALE_FACTOR", None)
from PySide6.QtWidgets import QApplication
from missive.presentation import uiscale
QApplication.setApplicationName("Name")
QApplication.setOrganizationName("Org")
QApplication.setDesktopFileName("io.example.Name")
uiscale.apply_before_app()
app = QApplication([])
print(app.applicationName(), app.organizationName(), app.desktopFileName())
"""
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=60)
    assert done.stdout.strip().endswith("Name Org io.example.Name"), done.stdout + done.stderr
