from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from missive.presentation.qt_app import create_application


def _window():
    app = create_application(["test"])
    window = QWidget()
    column = QVBoxLayout(window)
    line, other, text = QLineEdit(), QLineEdit(), QPlainTextEdit()
    for w in (line, other, text):
        column.addWidget(w)
    window.show()
    window.activateWindow()
    return app, window, line, other, text


def _focus(app, widget):
    widget.setFocus()
    for _turn in range(40):
        if QApplication.focusWidget() is widget:
            return
        QTest.qWait(25)


def test_enter_in_a_one_line_box_lets_go_of_it():
    app, window, line, _other, _text = _window()
    pressed = []
    line.returnPressed.connect(lambda: pressed.append(True))
    line.setText("hello")
    _focus(app, line)
    line.selectAll()
    QTest.keyClick(line, Qt.Key_Return)
    QTest.qWait(50)
    assert pressed and not line.hasFocus() and not line.hasSelectedText()
    assert line.text() == "hello"


def test_the_keypad_enter_does_the_same():
    app, window, line, _other, _text = _window()
    _focus(app, line)
    QTest.keyClick(line, Qt.Key_Enter)
    QTest.qWait(50)
    assert not line.hasFocus()


def test_enter_in_a_multi_line_box_still_makes_a_new_line():
    app, window, _line, _other, text = _window()
    _focus(app, text)
    QTest.keyClick(text, Qt.Key_Return)
    QTest.qWait(50)
    assert text.hasFocus() and text.toPlainText() == "\n"


def test_other_keys_keep_the_focus():
    app, window, line, _other, _text = _window()
    _focus(app, line)
    QTest.keyClick(line, Qt.Key_A)
    QTest.qWait(50)
    assert line.hasFocus() and line.text() == "a"
