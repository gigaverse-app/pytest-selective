"""Static pytest plugin declarations, without importing application code.

pytest accepts a comma-separated string or a sequence of names. Computed
declarations stay unknown: dropping them could silently exclude affected tests.
"""

import ast
from collections.abc import Iterator

from pytest_selective.ast_imports import parse_ast


def registers_plugins(source: bytes) -> bool:
    """Whether collecting this module may change the session's plugins."""
    if b"pytest_plugins" not in source:
        return False
    try:
        names = declared_plugins(parse_ast(source))
    except (SyntaxError, ValueError):
        return True
    return names is None or bool(names)


def _statements(tree: ast.AST) -> Iterator[ast.stmt]:
    pending = list(reversed(getattr(tree, "body", [])))
    while pending:
        node = pending.pop()
        if isinstance(node, ast.stmt):
            yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("finalbody", "orelse", "handlers", "cases", "body"):
            pending.extend(reversed(getattr(node, field, [])))


def _value(node: ast.expr) -> str | list[str] | None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if node.value is None:
            return []
    if isinstance(node, (ast.List, ast.Tuple)):
        if all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
            return [item.value for item in node.elts]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _value(node.left), _value(node.right)
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
    return None


def _name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "pytest_plugins"


def _mentions(node: ast.AST) -> bool:
    return any(_name(child) for child in ast.walk(node))


def declared_plugins(tree: ast.Module) -> list[str] | None:
    """Union module-scope declarations across branches; None means unproven.

    Reassignments retain old candidates conservatively. Function/class locals
    are not module declarations. Plugins may recursively register other plugins.
    """
    result: set[str] = set()
    for statement in _statements(tree):
        value: ast.expr | None = None
        append = False
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            if any(not _name(target) and _mentions(target) for target in targets):
                return None
            if any(_name(target) for target in targets):
                if len(targets) != 1:
                    return None  # Another binding can mutate the same list.
                value = statement.value
            elif _mentions(statement.value):
                return None  # Escaped through an alias or arbitrary callback.
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)) and _name(statement.target):
            value = statement.value
            if isinstance(statement, ast.AugAssign) and not isinstance(statement.op, ast.Add):
                return None
        elif isinstance(statement, ast.Expr) and isinstance(call := statement.value, ast.Call):
            if isinstance(call.func, ast.Attribute) and _name(call.func.value):
                if call.func.attr not in {"append", "extend"} or len(call.args) != 1 or call.keywords:
                    return None
                value = call.args[0]
                append = call.func.attr == "append"
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            if any((alias.asname or alias.name) == "pytest_plugins" for alias in statement.names):
                return None
        if value is None:
            continue
        names = _value(value)
        if names is None or (append and not isinstance(names, str)):
            return None
        result.update([names] if append else names.split(",") if isinstance(names, str) else names)
    return sorted(result)
