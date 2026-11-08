"""Drives pytest-selective's planner through the model's commits. No selection logic lives here."""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import pytest
from selection_driver import SelectionDriver, View

from pytest_quint_connect import HistoryContext
from pytest_selective.impact_graph import GraphCache, union_edges
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.impact_selection import affected
from tests.testing.git_repo import commit, init, write

# Model file name -> repository path.
PATHS = {
    "alpha": "src/pkg/alpha.py",
    "beta": "src/pkg/beta.py",
    "gamma": "src/pkg/gamma.py",
    "conftest": "tests/conftest.py",
    "test_one": "tests/test_one.py",
    "test_two": "tests/test_two.py",
    "table": "data/table.json",
}
NAMES = {path: name for name, path in PATHS.items()}
INITIAL_IMPORTS = {"test_one": {"alpha"}, "alpha": {"beta"}, "test_two": {"gamma"}}
CONFIG = ImpactConfig(module_roots=["src", "."], test_roots=["tests"])


def _one_hop(edges: dict[str, list[str]], starts: set[str]) -> set[str]:
    return starts | {reader for start in starts for reader in edges.get(start, ())}


# Deliberate faults in the planner. A mutant's case passes only when some history's
# selection differs from the model's.
MUTANTS: dict[str, tuple[str, Callable[..., object]]] = {
    # Forget the base tree: a deleted module's former importers are no longer reached.
    "head-edges-only": ("pytest_selective.impact_selection.union_edges", lambda *trees: union_edges(trees[-1])),
    # Stop after the files that import a changed file directly.
    "direct-importers-only": ("pytest_selective.impact_selection.reachable", _one_hop),
    # Treat requirements.txt like any other unreferenced file.
    "global-inputs-ignored": ("pytest_selective.impact_selection.matches", lambda path, patterns: False),
}


class RepositoryDriver(SelectionDriver):
    """Commits each model step to a real repository and selects between consecutive commits."""

    def __init__(self, context: HistoryContext) -> None:
        self.root = context.work_dir / "repo"
        self._resources = ExitStack()
        self.cache = GraphCache(context.work_dir / "graph.sqlite3")
        self._resources.callback(self.cache.close)
        if context.mutant:
            target, fault = MUTANTS[context.mutant]
            self._resources.enter_context(mock.patch(target, fault))
        self.imports: dict[str, set[str]] = {}
        self.versions = dict.fromkeys(PATHS, 0)
        self.versions["requirements"] = 0
        self.head = ""
        self.view: View = {"mode": "none", "selected": frozenset()}

    def close(self) -> None:
        self._resources.close()

    def _write(self, name: str) -> None:
        version = self.versions[name]
        if name == "table":
            write(self.root, PATHS[name], f'{{"version": {version}}}\n')
            return
        lines = ["# gv:test-dependency: data/table.json"] if name == "test_two" else []
        lines += [f"import pkg.{target}" for target in sorted(self.imports.get(name, ()))]
        lines.append(f"VERSION = {version}")
        write(self.root, PATHS[name], "\n".join(lines) + "\n")

    def _write_requirements(self) -> None:
        write(self.root, "requirements.txt", f"# version {self.versions['requirements']}\n")

    def _commit(self) -> None:
        base, self.head = self.head, commit(self.root)
        report = affected(self.root, base, self.head, CONFIG, self.cache)
        self.view = {"mode": report.mode, "selected": frozenset(NAMES[path] for path in report.selected)}

    def init(self) -> None:
        init(self.root)
        self.imports = {name: set(targets) for name, targets in INITIAL_IMPORTS.items()}
        write(self.root, "src/pkg/__init__.py")
        for name in PATHS:
            self._write(name)
        self._write_requirements()
        self.head = commit(self.root)

    def edit(self, file: str) -> None:
        self.versions[file] += 1
        self._write(file)
        self._commit()

    def link(self, file: str, target: str) -> None:
        self.imports.setdefault(file, set()).add(target)
        self._write(file)
        self._commit()

    def unlink(self, file: str, target: str) -> None:
        self.imports[file].discard(target)
        self._write(file)
        self._commit()

    def remove(self, file: str) -> None:
        self.imports.pop(file, None)
        (self.root / PATHS[file]).unlink()
        self._commit()

    def restore(self, file: str) -> None:
        self._write(file)
        self._commit()

    def touchGlobal(self) -> None:
        self.versions["requirements"] += 1
        self._write_requirements()
        self._commit()

    def inspect(self) -> None:
        pass

    def observe(self) -> View:
        return self.view


@pytest.fixture
def repository_driver() -> Iterator[Callable[[HistoryContext], RepositoryDriver]]:
    yield RepositoryDriver
