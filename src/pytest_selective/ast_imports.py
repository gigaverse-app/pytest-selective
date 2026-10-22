"""Extract Python import statements without walking expression subtrees."""

import ast
from collections import deque
from collections.abc import Iterator
from pathlib import Path


def iter_imports(tree: ast.Module) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield all imports in the same breadth-first order as ``ast.walk``."""
    pending: deque[ast.AST] = deque([tree])
    while pending:
        node = pending.popleft()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        else:
            # Parsed Python expressions cannot contain import statements.
            # Keep the extra level for exception handlers and match cases so
            # pruning expressions preserves ast.walk's finding order.
            pending.extend(
                child
                for child in ast.iter_child_nodes(node)
                if isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case))
            )


def import_candidates(node: ast.Import | ast.ImportFrom, importer_package: str) -> set[str]:
    """
    Dotted module paths an import statement might load.

    ``from X import Y`` can bind either attribute ``Y`` of module ``X``
    or submodule ``X.Y`` — both are candidates; only ones that resolve
    to real files are judged.
    """
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if node.level:
        package_parts = importer_package.split(".") if importer_package else []
        if node.level - 1 > len(package_parts):
            return set()
        prefix_parts = package_parts[: len(package_parts) - (node.level - 1)]
        base = ".".join([*prefix_parts, node.module] if node.module else prefix_parts)
    else:
        base = node.module or ""
    candidates = {base} if base else set()
    for alias in node.names:
        if alias.name != "*":
            candidates.add(f"{base}.{alias.name}" if base else alias.name)
    return candidates


def module_file(repo_root: Path, dotted: str) -> Path | None:
    """
    Resolve a dotted module path to a repo file, if it exists.
    """
    base = repo_root.joinpath(*dotted.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None
