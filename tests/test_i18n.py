"""Every on-screen text needs a Russian and an Italian translation, with the same placeholders."""
import ast
import re
import string
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "missive"
ERROR_CLASSES = re.compile(r"(Error|NotFound|NotConnected)$")


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def ui_strings() -> set[str]:
    found = set()
    for path in (ROOT / "presentation").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("_", "N_") and node.args):
                text = _literal(node.args[0])
                if text:
                    found.add(text)
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "C_"
                    and len(node.args) == 2):
                context, text = _literal(node.args[0]), _literal(node.args[1])
                if context and text:
                    found.add(f"{context}|{text}")
    return found


def core_messages() -> set[str]:
    """Fixed error messages and sync-part names that the UI shows via _(str(e))."""
    found = set()
    for layer in ("domain", "application", "infrastructure"):
        for path in (ROOT / layer).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and node.args:
                    name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                    text = _literal(node.args[0])
                    if text and (ERROR_CLASSES.search(name) or name == "part"):
                        found.add(text)
    return found


def plural_words() -> set[str]:
    found = set()
    for path in (ROOT / "presentation").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "plural"
                    and len(node.args) >= 2):
                word = _literal(node.args[1])
                if word:
                    found.add(word)
    return found


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


FORMS = {"ru": 3, "it": 2}


@pytest.fixture(scope="module", params=sorted(FORMS))
def ru(request):
    """The catalogue under test (named ru for history): Russian, then Italian."""
    import importlib
    return importlib.import_module(f"missive.presentation.locales.{request.param}")


def test_every_ui_string_is_translated(ru):
    missing = sorted(ui_strings() - ru.MESSAGES.keys())
    assert not missing, "Missing translation for:\n" + "\n".join(missing)


def test_every_core_message_is_translated(ru):
    missing = sorted(core_messages() - ru.MESSAGES.keys())
    assert not missing, "Missing translation for:\n" + "\n".join(missing)


def test_every_plural_word_has_its_forms(ru):
    missing = sorted(plural_words() - ru.PLURALS.keys())
    assert not missing, "Missing plural forms for: " + ", ".join(missing)
    assert all(len(forms) == FORMS[ru.__name__[-2:]] for forms in ru.PLURALS.values())


def test_translations_keep_their_placeholders(ru):
    wrong = [k for k, v in ru.MESSAGES.items() if placeholders(k) != placeholders(v)]
    assert not wrong, "Placeholders differ in: " + "; ".join(wrong)


@pytest.mark.parametrize("n, form", [(1, 0), (21, 0), (2, 1), (4, 1), (22, 1), (5, 2), (11, 2),
                                     (12, 2), (14, 2), (25, 2), (0, 2), (111, 2), (101, 0)])
def test_russian_plural_rule(n, form):
    from missive.presentation.i18n import plural_form
    assert plural_form(n) == form


def test_nothing_in_the_ui_assigns_to_underscore():
    """`_` is the translation function. Using it as a throwaway variable anywhere in a
    function makes every `_("…")` call in that function crash (UnboundLocalError)."""
    offenders = []
    for path in (ROOT / "presentation").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name) and node.id == "_" and isinstance(node.ctx, ast.Store):
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.arg) and node.arg == "_":
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, "Don't use _ as a variable: " + ", ".join(offenders)


def test_italian_plural_rule():
    from missive.presentation import i18n
    i18n.install("it")
    try:
        assert [i18n._form(n) for n in (0, 1, 2, 5, 21)] == [1, 0, 1, 1, 1]
    finally:
        i18n.install("en")
