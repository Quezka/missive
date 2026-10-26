"""Enforce the dependency rule: source code dependencies only point inwards."""
import ast
import dataclasses
import enum
import inspect
import typing
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "missive"

# layer -> modules it must never import
FORBIDDEN = {
    "domain": ["missive.application", "missive.infrastructure", "missive.presentation",
               "missive.bootstrap", "PySide6", "sqlite3"],
    "application": ["missive.infrastructure", "missive.presentation", "missive.bootstrap",
                    "PySide6", "sqlite3"],
    "infrastructure": ["missive.presentation", "missive.bootstrap", "PySide6"],
    # The UI talks to use cases only; the enums and errors it needs are re-exported
    # by missive.application.types and missive.application.errors.
    "presentation": ["missive.domain", "missive.infrastructure", "missive.bootstrap", "sqlite3"],
}


def imports_of(path: Path) -> set[str]:
    parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
    package = ".".join(parts[:-1])  # for __init__.py this is the package itself
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                name = ".".join(base + ([node.module] if node.module else []))
            else:
                name = node.module
            found.add(name)
    return found


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_respects_dependency_rule(layer):
    violations = []
    for path in sorted((PACKAGE / layer).rglob("*.py")):
        for imported in imports_of(path):
            for banned in FORBIDDEN[layer]:
                if imported == banned or imported.startswith(banned + "."):
                    violations.append(f"{path.relative_to(PACKAGE)} imports {imported}")
    assert not violations, "\n".join(violations)

