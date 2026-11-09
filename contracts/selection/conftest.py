"""Drives pytest-selective's planner through the model's commits. No selection logic lives here."""

import fnmatch
import io
import json
import os
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from unittest import mock

import pytest
from pytest_quint_connect import HistoryContext
from selection_driver import Selection, SelectionDriver, View

from pytest_selective.git_operations import git, git_text
from pytest_selective.impact_graph import (
    DependencyDeclarationError,
    GraphCache,
    inventory,
    policy_fingerprints,
    union_edges,
    within,
)
from pytest_selective.impact_models import ImpactConfig, Snapshot
from pytest_selective.impact_selection import affected, base_snapshot
from tests.testing.git_repo import commit, init, write

# Model file name -> repository path.
PATHS = {
    "alpha": "src/pkg/alpha.py",
    "beta": "src/pkg/beta.py",
    "gamma": "src/pkg/gamma.py",
    "helper": "tests/helpers.py",
    "conftest": "tests/conftest.py",
    "subconftest": "tests/sub/conftest.py",
    "test_one": "tests/test_one.py",
    "test_two": "tests/test_two.py",
    "test_sub": "tests/sub/test_sub.py",
    "table": "data/table.json",
    "init": "src/pkg/__init__.py",
    "plugin": "plug.py",
}
NAMES = {path: name for name, path in PATHS.items()}
# How each model import target is spelled in source.
IMPORT_LINES = {
    "alpha": "import pkg.alpha",
    "beta": "import pkg.beta",
    "gamma": "import pkg.gamma",
    "helper": "import tests.helpers",
    "star": "from pkg import *",
    "helperBare": "import helpers",
}
# The fixture's pytest configuration: src and the root on sys.path, and a command-line plugin.
PYTEST_INI = "[pytest]\npythonpath = src .\naddopts = -p plug\n"
RUNTIME_DEPS = Path(__file__).with_name("runtime_deps.py")
# Repository files each test loads at runtime, by (Git tree id, test path). Trees repeat across
# histories, so one pytest run per tree serves every history that reaches it.
_RUNTIME: dict[tuple[str, str], frozenset[str]] = {}
INITIAL_IMPORTS = {"test_one": {"alpha"}, "alpha": {"beta"}, "test_two": {"gamma"}, "test_sub": {"helper"}}
INITIAL_DECLARATIONS = {"test_two": {"table"}}
# The model's fixed content reads: test_sub reads gamma's bytes, and the helper reads the table's.
CONTENT_SIDECARS = {
    "test_sub": (
        "tests/sub/test_sub.py.gv-dependency.yaml",
        "dependencies:\n"
        '  - inputs: ["//src/pkg/gamma.py"]\n'
        "    kind: content\n"
        "    reason: The test reads gamma's source as text.\n",
    ),
    "helper": (
        "tests/helpers.py.gv-dependency.yaml",
        "dependencies:\n"
        '  - inputs: ["//data/table.json"]\n'
        "    kind: content\n"
        "    reason: The helper loads the table.\n",
    ),
}
CONFIG = ImpactConfig(module_roots=["src", "."], test_roots=["tests"])
# The model's two configuration options, as edits of CONFIG.
NARROW_ROOTS = ["tests/sub"]
TABLE_GLOBAL = [*CONFIG.global_inputs, PATHS["table"]]
NO_SELECTION: Selection = {"mode": "none", "selected": frozenset()}


def _one_hop(edges: dict[str, list[str]], starts: set[str]) -> set[str]:
    return starts | {reader for start in starts for reader in edges.get(start, ())}


_snapshot = GraphCache.snapshot


def _parseable_snapshot(self: GraphCache, repo, revision: str, config: ImpactConfig) -> Snapshot:
    snapshot = _snapshot(self, repo, revision, config)
    opaque = {
        path: [r for r in reasons if not r.startswith("cannot parse:")] for path, reasons in snapshot.opaque.items()
    }
    return snapshot.model_copy(update={"opaque": opaque})


class _AssumesConsecutiveBase:
    """A planner that takes every base to be the head it planned last: right only between neighbours."""

    def __init__(self) -> None:
        self.head: Snapshot | None = None
        self.previous: Snapshot | None = None

    def snapshot(self, cache: GraphCache, repo, revision: str, config: ImpactConfig) -> Snapshot:
        # affected() reads the head before the base, so this is the head of the run in progress.
        self.head = _snapshot(cache, repo, revision, config)
        return self.head

    def base_snapshot(self, repo, base: str, config: ImpactConfig, cache: GraphCache, config_path) -> Snapshot:
        head, previous = self.head, self.previous
        self.previous = head
        return previous if previous is not None else base_snapshot(repo, base, config, cache, config_path)

    def patches(self) -> list[tuple[str, object]]:
        # A plain function, so that the patched method still receives the cache as its first argument.
        def snapshot(cache: GraphCache, repo, revision: str, config: ImpactConfig) -> Snapshot:
            return self.snapshot(cache, repo, revision, config)

        return [
            ("pytest_selective.impact_graph.GraphCache.snapshot", snapshot),
            ("pytest_selective.impact_selection.base_snapshot", self.base_snapshot),
        ]


_dump = ImpactConfig.model_dump_json
_get = GraphCache.get
_parse_python = GraphCache.parse_python


def _key_without_test_roots(self: ImpactConfig, **options) -> str:
    # The graph key hashes the configuration with these fields excluded; leave test_roots out too.
    exclude = options.get("exclude")
    if isinstance(exclude, set) and "audit_exemptions" in exclude:
        options["exclude"] = exclude | {"test_roots"}
    return _dump(self, **options)


def _unchecked_get(self: GraphCache, key: str) -> str | None:
    row = self.connection.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


def _parse_by_path(self: GraphCache, repo, files: dict[str, str]):
    # Remember the first blob seen at each path and parse that one forever after.
    first = self.__dict__.setdefault("_first_blob_at_path", {})
    stale = {path: first.setdefault(path, oid) for path, oid in files.items()}
    parsed = _parse_python(self, repo, stale)
    return {files[path]: parsed[oid] for path, oid in stale.items() if oid in parsed}


# Deliberate faults in the planner, each a list of (target, replacement) patches, built once per
# history. A mutant's case passes only when some history's selection differs from the model's.
MUTANTS: dict[str, Callable[[], list[tuple[str, object]]]] = {
    # Forget the base tree: a deleted module's former importers are no longer reached.
    "head-edges-only": lambda: [
        ("pytest_selective.impact_selection.union_edges", lambda *trees: union_edges(trees[-1]))
    ],
    # Stop after the files that import a changed file directly.
    "direct-importers-only": lambda: [("pytest_selective.impact_selection.reachable", _one_hop)],
    # Treat requirements.txt like any other unreferenced file.
    "global-inputs-ignored": lambda: [("pytest_selective.impact_selection.matches", lambda path, patterns: False)],
    # Read a content-kind declaration as an import: it then follows the read file's imports.
    "content-follows-imports": lambda: [
        ("pytest_selective.impact_graph.contents_node", lambda path: path),
        ("pytest_selective.impact_declarations.contents_node", lambda path: path),
    ],
    # Scope every conftest to its top-level directory, so tests/sub/conftest.py reaches every test.
    "conftest-scope-collapsed": lambda: [
        ("pytest_selective.impact_graph.within", lambda path, root: within(path, root.split("/")[0]))
    ],
    # Treat an unparseable file as one that imports nothing.
    "parse-errors-ignored": lambda: [("pytest_selective.impact_graph.GraphCache.snapshot", _parseable_snapshot)],
    # Plan every run against the head of the run before it, as an incremental cache might.
    "assumes-consecutive-base": lambda: _AssumesConsecutiveBase().patches(),
    # Leave test_roots out of the cached graph's key.
    "cache-key-omits-test-roots": lambda: [
        ("pytest_selective.impact_models.ImpactConfig.model_dump_json", _key_without_test_roots)
    ],
    # Cache parsed files by path, not by content.
    "parse-cache-keyed-by-path": lambda: [("pytest_selective.impact_graph.GraphCache.parse_python", _parse_by_path)],
    # Return stored entries without checking their checksum.
    "cache-checksum-ignored": lambda: [("pytest_selective.impact_graph.GraphCache.get", _unchecked_get)],
    # The three bugs the runtime check found, each put back exactly as it was before its fix.
    "star-exports-ignored": lambda: [
        ("pytest_selective.impact_graph.star_import_candidates", lambda *arguments, **options: set())
    ],
    "addopts-plugins-ignored": lambda: [("pytest_selective.impact_graph.command_line_plugins", lambda policies: set())],
    "prepend-roots-ignored": lambda: [("pytest_selective.impact_graph.prepend_roots", lambda python_files, config: [])],
    "literal-reads-ignored": lambda: [
        ("pytest_selective.impact_graph.literal_read_targets", lambda reader, literal, files: set())
    ],
}


class RepositoryDriver(SelectionDriver):
    """Commits each model step to a real repository and selects against the previous and the first commit."""

    def __init__(self, context: HistoryContext) -> None:
        self.root = context.work_dir / "repo"
        self._resources = ExitStack()
        self.cache_path = context.work_dir / "graph.sqlite3"
        self.cache = GraphCache(self.cache_path)
        self._resources.callback(lambda: self.cache.close())
        for target, replacement in MUTANTS[context.mutant]() if context.mutant else ():
            self._resources.enter_context(mock.patch(target, replacement))
        self.imports: dict[str, set[str]] = {}
        self.declared: dict[str, set[str]] = {}
        self.broken: set[str] = set()
        self.reads: set[str] = set()
        self.versions = dict.fromkeys(PATHS, 0)
        self.requirements = 0
        self.config = CONFIG
        self.trees = context.work_dir / "trees"
        # Mutants are judged by the model; the runtime check describes the real planner only.
        self.check_runtime = context.mutant is None
        self.start = self.previous = self.head = ""
        self.view: View = {**NO_SELECTION, "sinceStart": NO_SELECTION, "missed": frozenset()}

    def close(self) -> None:
        self._resources.close()

    def _write(self, name: str) -> None:
        version = self.versions[name]
        if name == "table":
            write(self.root, PATHS[name], f'{{"version": {version}}}\n')
            return
        lines = ['__all__ = ["alpha"]'] if name == "init" else []
        lines += [f"# gv:test-dependency: {PATHS[target]}" for target in sorted(self.declared.get(name, ()))]
        lines += [IMPORT_LINES[target] for target in sorted(self.imports.get(name, ()))]
        lines.append(f"VERSION = {version}")
        if name in self.reads:
            lines.append(f'TABLE = open("{PATHS["table"]}", encoding="utf-8").read()')
        if name in self.broken:
            lines.append("def broken(:")
        write(self.root, PATHS[name], "\n".join(lines) + "\n")

    def _write_requirements(self) -> None:
        write(self.root, "requirements.txt", f"# version {self.requirements}\n")

    def _select(self, base: str) -> Selection:
        try:
            report = affected(self.root, base, self.head, self.config, self.cache)
        except DependencyDeclarationError as error:
            # Only the hard error the model describes; any other declaration error is a failure.
            if not str(error).startswith("Unparseable Python dependency"):
                raise
            return {"mode": "error", "selected": frozenset()}
        return {"mode": report.mode, "selected": frozenset(NAMES[path] for path in report.selected)}

    def _commit(self, *names: str) -> None:
        for name in names:
            self._write(name)
        self.previous, self.head = self.head, commit(self.root)
        self._replan()

    def _replan(self) -> None:
        latest, since_start = self._select(self.previous), self._select(self.start)
        missed = self._missed(self.previous, latest) | self._missed(self.start, since_start)
        self.view = {**latest, "sinceStart": since_start, "missed": frozenset(missed)}

    def _runtime(self, revision: str, tests: list[str]) -> dict[str, frozenset[str]]:
        """What pytest's collection of each test file imports or opens in the tree at ``revision``."""
        tree = git_text(self.root, "rev-parse", f"{revision}^{{tree}}").strip()
        missing = [test for test in tests if (tree, test) not in _RUNTIME]
        if missing:
            directory = self.trees / tree
            if not directory.exists():
                archive = git(self.root, "archive", "--format=tar", revision)
                with tarfile.open(fileobj=io.BytesIO(archive)) as members:
                    members.extractall(directory, filter="data")
            environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            run = subprocess.run(
                [sys.executable, "-I", "-B", str(RUNTIME_DEPS), str(directory), *missing],
                capture_output=True,
                text=True,
                env=environment,
            )
            line = next((row for row in run.stdout.splitlines() if row.startswith("RUNTIME_DEPS ")), None)
            assert line is not None, f"runtime dependency run failed:\n{run.stdout[-2000:]}\n{run.stderr[-2000:]}"
            for test, files in json.loads(line.removeprefix("RUNTIME_DEPS ")).items():
                _RUNTIME[(tree, test)] = frozenset(files)
        return {test: _RUNTIME[(tree, test)] for test in tests}

    def _tests(self, revision: str) -> list[str]:
        files = git_text(self.root, "ls-tree", "-r", "--name-only", revision).splitlines()
        return [
            path
            for path in files
            if any(within(path, root) for root in self.config.test_roots)
            and any(fnmatch.fnmatch(PurePosixPath(path).name, pattern) for pattern in self.config.test_patterns)
        ]

    def _missed(self, base: str, selection: Selection) -> set[str]:
        """Tests whose runtime dependencies at base or head include a changed file, but were not selected."""
        if not self.check_runtime or selection["mode"] == "error" or base == self.head:
            return set()
        changed = set(git_text(self.root, "diff", "--name-only", "--no-renames", base, self.head).splitlines())
        tests = self._tests(self.head)
        at_head = self._runtime(self.head, tests)
        base_tests = set(self._tests(base))
        at_base = self._runtime(base, [test for test in tests if test in base_tests])
        needed = {test for test in tests if (at_head[test] | at_base.get(test, frozenset())) & changed}
        return {NAMES[test] for test in needed} - set(selection["selected"])

    def init(self) -> None:
        init(self.root)
        self.imports = {name: set(targets) for name, targets in INITIAL_IMPORTS.items()}
        self.declared = {name: set(targets) for name, targets in INITIAL_DECLARATIONS.items()}
        write(self.root, "pytest.ini", PYTEST_INI)
        for sidecar in CONTENT_SIDECARS.values():
            write(self.root, *sidecar)
        for name in PATHS:
            self._write(name)
        self._write_requirements()
        self.start = self.previous = self.head = commit(self.root)
        # The fixture's pytest.ini never changes; record its reviewed collection-policy fingerprint.
        policy = policy_fingerprints(self.root, inventory(self.root, self.head))
        self.config = self.config.model_copy(update={"pytest_policy": policy})

    def edit(self, file: str) -> None:
        self.versions[file] += 1
        self._commit(file)

    def link(self, file: str, target: str) -> None:
        self.imports.setdefault(file, set()).add(target)
        self._commit(file)

    def unlink(self, file: str, target: str) -> None:
        self.imports[file].discard(target)
        self._commit(file)

    def remove(self, file: str) -> None:
        self.imports.pop(file, None)
        self.declared.pop(file, None)
        self.broken.discard(file)
        self.reads.discard(file)
        (self.root / PATHS[file]).unlink()
        if file in CONTENT_SIDECARS:
            (self.root / CONTENT_SIDECARS[file][0]).unlink()
        self._commit()

    def restore(self, file: str) -> None:
        if file in CONTENT_SIDECARS:
            write(self.root, *CONTENT_SIDECARS[file])
        self._commit(file)

    def declare(self, file: str, target: str) -> None:
        self.declared.setdefault(file, set()).add(target)
        self._commit(file)

    def undeclare(self, file: str, target: str) -> None:
        self.declared[file].discard(target)
        self._commit(file)

    def break_syntax(self, file: str) -> None:
        self.broken.add(file)
        self._commit(file)

    def repair(self, file: str) -> None:
        self.broken.discard(file)
        self._commit(file)

    def read_table(self, file: str) -> None:
        self.reads.add(file)
        self._commit(file)

    def touch_global(self) -> None:
        self.requirements += 1
        self._write_requirements()
        self._commit()

    def toggle_config(self, option: str) -> None:
        if option == "narrow":
            roots = CONFIG.test_roots if self.config.test_roots == NARROW_ROOTS else NARROW_ROOTS
            self.config = self.config.model_copy(update={"test_roots": roots})
        else:
            inputs = CONFIG.global_inputs if self.config.global_inputs == TABLE_GLOBAL else TABLE_GLOBAL
            self.config = self.config.model_copy(update={"global_inputs": inputs})
        self._replan()

    def restart(self) -> None:
        self.cache.close()
        self.cache = GraphCache(self.cache_path)
        self._replan()

    def corrupt(self) -> None:
        rows = self.cache.connection.execute("SELECT key, value FROM cache WHERE key LIKE '%:graph:%'").fetchall()
        for key, value in rows:
            graph = json.loads(value)
            graph["edges"] = {}
            # The stored checksum still describes the original value.
            self.cache.connection.execute("UPDATE cache SET value=? WHERE key=?", (json.dumps(graph), key))
        self.cache.connection.commit()
        self._replan()

    def inspect(self) -> None:
        pass

    def observe(self) -> View:
        return self.view


@pytest.fixture
def repository_driver() -> Iterator[Callable[[HistoryContext], RepositoryDriver]]:
    yield RepositoryDriver
