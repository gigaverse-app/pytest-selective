"""
Enforce the test-file isolation invariant: test modules never import test modules.

A test module (``test_*.py`` / ``*_test.py``) that imports another test module
couples the two files' behavior, so re-running only the changed file no longer
proves the unchanged one still passes. Keeping test modules import-isolated is
what makes file-level CI test selection sound: a diff touching only
``tests/x/test_y.py`` can re-run exactly that file.

Shared code belongs in non-test modules instead — ``conftest.py`` for pytest
fixtures at the narrowest useful scope, and plainly named helper modules
(``helpers*.py``, ``fakes*.py``, ``factories*.py``, ...) either inside the test
directory that owns them or in the repo's shared test-resource packages
(``tests/helpers/``, ``tests/fakes/``, ``tests/fixtures/``, ``tests/test_data/``).

The check is import-graph based, not name based: ``from tests.test_ci.helpers
import x`` is fine (the imported *module* is ``helpers``) even though a package
on the path is named ``test_ci``; ``from tests.test_ci.test_foo import x`` is a
violation because the imported module is the test file ``test_foo``.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pytest_selective.ast_imports import import_candidates, iter_imports, module_file, parse_ast
from pytest_selective.test_inventory import TEST_FILE_PATTERNS, is_test_module_name


class TestImportViolation(BaseModel):
    """One test module importing another test module."""

    model_config = ConfigDict(frozen=True)

    importer: Path
    line: int
    imported_module: str

    def __str__(self) -> str:
        return f"{self.importer}:{self.line}: imports test module {self.imported_module!r}"


def is_test_module(path: Path) -> bool:
    return is_test_module_name(path.name)


def discover_test_modules(test_roots: list[Path]) -> list[Path]:
    discovered: set[Path] = set()
    for root in test_roots:
        if root.is_file():
            if is_test_module(root):
                discovered.add(root)
            continue
        for pattern in TEST_FILE_PATTERNS:
            discovered.update(root.rglob(pattern))
    return sorted(discovered)


def find_test_import_violations(
    repo_root: Path,
    test_roots: list[Path],
) -> list[TestImportViolation]:
    """
    Scan every test module under the roots for imports of other test
    modules.

    ``repo_root`` is the directory absolute imports resolve against (the
    pytest rootdir); ``test_roots`` are the directories holding test modules.
    """
    repo_root = repo_root.resolve()
    test_modules = discover_test_modules([repo_root / root for root in test_roots])
    # Only modules under the scanned roots count as test modules: production
    # code is free to end in `_test.py`-shaped names (e.g. a `stress_test`
    # command) without tripping the invariant.
    test_module_files = {test_file.resolve() for test_file in test_modules}

    # Module resolution depends only on this scan's root and dotted name.
    # Keep the cache local so subsequent scans see added/removed files.
    @cache
    def resolved_module(dotted: str) -> Path | None:
        imported = module_file(repo_root, dotted)
        return imported.resolve() if imported is not None else None

    violations: list[TestImportViolation] = []
    for test_file in test_modules:
        resolved_test_file = test_file.resolve()
        importer_package = ".".join(resolved_test_file.relative_to(repo_root).parent.parts)
        tree = parse_ast(test_file.read_bytes(), filename=str(test_file))
        for node in iter_imports(tree):
            for dotted in sorted(import_candidates(node, importer_package)):
                imported = resolved_module(dotted)
                if imported is None or imported == resolved_test_file:
                    continue
                if imported in test_module_files:
                    violations.append(
                        TestImportViolation(
                            importer=test_file.relative_to(repo_root),
                            line=node.lineno,
                            imported_module=dotted,
                        )
                    )
    return violations


def assert_test_file_isolation(repo_root: Path, test_roots: list[Path]) -> None:
    """
    Raise with every violation listed; the natural single-call consumer
    API."""
    violations = find_test_import_violations(repo_root, test_roots)
    if violations:
        summary = "\n".join(str(violation) for violation in violations)
        raise AssertionError(
            "test modules must not import other test modules "
            f"(move shared code to conftest.py or a non-test helper module):\n{summary}"
        )
