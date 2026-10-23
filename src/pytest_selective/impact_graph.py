"""
Import graphs from immutable Git trees; no imports execute during planning.

Blob parsing and resolved graphs have distinct cache keys. Every new tree
resolves all saved candidates again, including previously unresolved names.
"""

import ast
import configparser
import fnmatch
import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import tokenize
import tomllib
import unicodedata
from collections import deque
from pathlib import Path, PurePosixPath
from typing import TypeVar

from pytest_selective.ast_imports import import_candidates, iter_imports, parse_ast
from pytest_selective.impact_declarations import (
    DependencyDeclarationError,
    is_declaration,
    manifest_edges,
    match_inputs,
)
from pytest_selective.impact_models import (
    DeferredRoute,
    DependencyComment,
    EdgeKind,
    GitTree,
    ImpactConfig,
    ImportSpec,
    ParsedSource,
    PathStep,
    Snapshot,
    contents_node,
    file_of,
)
from pytest_selective.pytest_plugins import declared_plugins

VERSION = "20"
OPAQUE_CALLS = {
    "__import__",
    "import_module",
    "import_string",
    "spec_from_file_location",
    "read_text",
    "read_bytes",
    "open",
    "Popen",
    "check_call",
    "check_output",
    "exec",
    "eval",
    "run_module",
    "run_path",
    "walk",
    "rglob",
    "glob",
}
MODULE_STRING_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")


def is_module_string(value: str) -> bool:
    """
    Whether a string literal may name a module and so creates a dependency edge.

    Re-exports, patch targets, pytest_plugins and framework registrations commonly contain
    literal dotted names instead of import statements.
    """
    return "." in value and len(value) < 300 and set(value) <= MODULE_STRING_CHARS


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def within(path: str, root: str) -> bool:
    return root == "." or path == root or path.startswith(root.rstrip("/") + "/")


def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=data,
        capture_output=True,
        check=True,
        env=git_environment(),
    ).stdout


def git_environment() -> dict[str, str]:
    """Explicit repository paths win over location variables inherited from hooks."""
    locations = {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_GRAFT_FILE",
    }
    return {name: value for name, value in os.environ.items() if name not in locations}


CacheKey = TypeVar("CacheKey")
CacheValue = TypeVar("CacheValue")
FULL_OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
CACHED_OBJECTS = 1024
# One plan lists the same revisions several times, and each Git process costs ~40 ms on
# Windows. Both maps are content-addressed: a commit id names one tree, a tree one listing.
# Commit ids stay per repository, so an object another repository lacks still fails there.
_commit_trees: dict[tuple[str, str], str] = {}
_tree_listings: dict[str, bytes] = {}


def _remember(cache: dict[CacheKey, CacheValue], key: CacheKey, value: CacheValue) -> None:
    if len(cache) >= CACHED_OBJECTS:
        cache.clear()
    cache[key] = value


def inventory(repo: Path, revision: str) -> GitTree:
    commit_key = (str(repo), revision)
    tree = _commit_trees.get(commit_key)
    if tree is None:
        tree = git(repo, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{tree}}").decode().strip()
        if FULL_OBJECT_ID.fullmatch(revision):
            _remember(_commit_trees, commit_key, tree)
    listing = _tree_listings.get(tree)
    if listing is None:
        listing = git(repo, "ls-tree", "-rz", tree)
        _remember(_tree_listings, tree, listing)
    files: dict[str, str] = {}
    links: list[str] = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        relative_name = name.decode("utf-8")
        if mode == "120000" and not PurePosixPath(relative_name).suffix:
            links.append(relative_name)
        if kind != "blob" or (mode not in {"100644", "100755"} and name.endswith(b".py")):
            raise ValueError(f"unsupported Git entry {name!r}: {mode} (symlink/submodule)")
        files[name.decode("utf-8")] = oid
    return GitTree(tree=tree, files=files, links=links)


def blobs(repo: Path, ids: set[str]) -> dict[str, bytes]:
    if not ids:
        return {}
    output = git(repo, "cat-file", "--batch", data=("\n".join(sorted(ids)) + "\n").encode())
    result: dict[str, bytes] = {}
    offset = 0
    for _ in ids:
        end = output.index(b"\n", offset)
        oid, kind, size = output[offset:end].split()
        if kind != b"blob":
            raise ValueError("Git object is not a blob")
        offset = end + 1
        length = int(size)
        result[oid.decode()] = output[offset : offset + length]
        offset += length + 1
    return result


def pytest_policies(repo: Path, files: dict[str, str], extra_files: tuple[str, ...] = ()) -> dict[str, str]:
    """
    Canonical JSON of the pytest configuration in each file pytest reads it from.

    One owner for which files carry pytest configuration and how each is read, shared by the
    review fingerprints and by any rule that must inspect what that configuration loads.
    """
    # Collection can choose a nested/hidden config, even an empty one. Track all
    # conventional candidates; caller-supplied -c files are opaque global policy.
    if missing := set(extra_files) - files.keys():
        raise ValueError(f"declared pytest configuration missing from committed tree: {sorted(missing)}")
    names = {"pyproject.toml", "pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "setup.cfg", "tox.ini"}
    paths = {path: oid for path, oid in files.items() if PurePosixPath(path).name in names or path in extra_files}
    contents = blobs(repo, set(paths.values()))
    policies: dict[str, str] = {}
    for path, oid in paths.items():
        source = contents[oid].decode("utf-8-sig")
        if path in extra_files:
            # No format guess for pytest -c: every byte may affect a plugin.
            policies[path] = json.dumps(source)
            continue
        if path.endswith(".toml"):
            document = tomllib.loads(source)
            policy = (
                document.get("tool", {}).get("pytest", {})
                if PurePosixPath(path).name == "pyproject.toml"
                else document.get("pytest", {})
            )
            canonical = json.dumps(policy, sort_keys=True)
        else:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(source)
            policy_sections = {
                section: dict(parser[section]) for section in parser.sections() if section in {"pytest", "tool:pytest"}
            }
            canonical = json.dumps(policy_sections, sort_keys=True)
        policies[path] = canonical
    return policies


def policy_fingerprints(repo: Path, tree: GitTree, extra_files: tuple[str, ...] = ()) -> dict[str, str]:
    return {
        path: hashlib.sha256(canonical.encode()).hexdigest()
        for path, canonical in pytest_policies(repo, tree.files, extra_files).items()
    }


def dependency_comment(text: str, line: int) -> DependencyComment | None:
    text = text.removeprefix("#").strip()
    return DependencyComment(line=line, text=text) if text.startswith("gv:test-dependency") else None


def dependency_comments(source: bytes) -> list[DependencyComment]:
    comments: list[DependencyComment] = []
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
        text = source.decode(encoding)
        # Most files have no declarations. Decode before the cheap prefilter so
        # source encoding cookies cannot conceal a real marker from analysis.
        if "gv:test-dependency" not in text:
            return comments
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                if comment := dependency_comment(token.string, token.start[0]):
                    comments.append(comment)
    except (tokenize.TokenError, SyntaxError, UnicodeError):
        # The AST parse diagnostic owns malformed Python. Keep any actual
        # declarations found before the tokenization error for validation.
        pass
    return comments


def add_sidecar_edges(repo: Path, tree: str, files: dict[str, str], snapshot: Snapshot) -> None:
    sidecars = {path: oid for path, oid in files.items() if is_declaration(path)}
    contents = blobs(repo, set(sidecars.values()))
    for path, oid in sorted(sidecars.items()):
        for reader, dependencies in manifest_edges(path, contents[oid], tree, set(files)).items():
            snapshot.edges[reader] = sorted(set(snapshot.edges.get(reader, [])) | dependencies)


def declared_inputs(comment: DependencyComment, files: dict[str, str], location: str) -> set[str]:
    prefix = "gv:test-dependency:"
    if not comment.text.startswith(prefix):
        raise DependencyDeclarationError(
            f"{location}:{comment.line}: invalid test dependency {comment.text!r}; expected one repository-relative path or glob"
        )
    return match_inputs(comment.text.removeprefix(prefix).strip(), set(files), f"{location}:{comment.line}")


def parse_source(source: bytes) -> ParsedSource:
    dependencies = dependency_comments(source)
    try:
        tree = parse_ast(source)
    except (SyntaxError, ValueError) as error:
        return ParsedSource(
            imports=[], strings=[], opaque=[f"cannot parse: {error}"], pytest_plugin=False, dependencies=dependencies
        )
    # Reuse one breadth-first traversal for every fact extracted from this blob.
    # Large expression subtrees used to be walked repeatedly for assignments,
    # imports, function names and call/string dependencies.
    nodes = list(ast.walk(tree))
    import_nodes = [node for node in nodes if isinstance(node, (ast.Import, ast.ImportFrom))]
    # Django stores this module name; assigning it does not execute its routes.
    # Keep the default graph conservative unless the consumer supplies the policy.
    registrations = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "ROOT_URLCONF"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    writes = sum(
        isinstance(node, ast.Name) and node.id == "ROOT_URLCONF" and isinstance(node.ctx, ast.Store) for node in nodes
    )
    registration = registrations[0].value if len(registrations) == writes == 1 else None
    imports = [
        ImportSpec(module="", names=[alias.name for alias in node.names])
        if isinstance(node, ast.Import)
        else ImportSpec(module=node.module or "", names=[alias.name for alias in node.names], level=node.level)
        for node in import_nodes
    ]
    strings: set[str] = set()
    opaque: set[str] = set()
    plugin = False
    aliases = {
        alias.asname or alias.name: alias.name
        for node in import_nodes
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    for statement in import_nodes:
        if isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                aliases[alias.asname or alias.name] = f"{statement.module}.{alias.name}"
    local_functions = {node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not registration:
            if is_module_string(node.value):
                strings.add(node.value)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("pytest_"):
            plugin = True
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        attributes: list[str] = []
        while isinstance(function, ast.Attribute):
            attributes.insert(0, function.attr)
            function = function.value
        owner = aliases.get(function.id, function.id) if isinstance(function, ast.Name) else ""
        qualified = ".".join([owner, *attributes])
        name = qualified.rsplit(".", 1)[-1]
        is_ast_walk = (
            name == "walk"
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ast"
        )
        is_ast_walk = is_ast_walk or (name == "walk" and isinstance(node.func, ast.Name) and name in local_functions)
        is_builtin_code = name in {"exec", "eval"} and isinstance(node.func, ast.Name)
        subprocess_run = qualified.startswith("subprocess.") or qualified in {"os.system", "os.popen"}
        mode = (
            node.args[1]
            if len(node.args) > 1
            else next((keyword.value for keyword in node.keywords if keyword.arg == "mode"), None)
        )
        write_only = (
            qualified in {"open", "builtins.open", "io.open"}
            and isinstance(mode, ast.Constant)
            and isinstance(mode.value, str)
            and "+" not in mode.value
            and any(flag in mode.value for flag in "wax")
        )
        if write_only:
            continue
        if (
            (name in OPAQUE_CALLS or subprocess_run)
            and not is_ast_walk
            and (name not in {"exec", "eval"} or is_builtin_code)
        ):
            literal_import = (
                name in {"__import__", "import_module", "import_string"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            )
            if literal_import:
                argument = node.args[0]
                assert isinstance(argument, ast.Constant)
                strings.add(str(argument.value))
                if str(argument.value).startswith("."):
                    opaque.add(f"relative dynamic import at line {node.lineno}")
            else:
                opaque.add(f"{name} at line {node.lineno}")
    return ParsedSource(
        registered_plugins=declared_plugins(tree) if b"pytest_plugins" in source else [],
        django_urlconf=str(registration.value) if isinstance(registration, ast.Constant) else None,
        imports=imports,
        strings=sorted(strings),
        opaque=sorted(opaque),
        pytest_plugin=plugin,
        dependencies=dependencies,
    )


def _cache_prefix() -> str:
    """Namespace for cache records: an analyzer or grammar change must never reuse old parses."""
    return f"{VERSION}:{sys.version_info[:2]}:"


class GraphCache:
    """Optional performance state, never evidence that a test passed."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, digest TEXT)")
        self.parsed_blobs = 0
        self.snapshot_hits = 0

    def close(self) -> None:
        # Bound transport cost independently of repository age or push count.
        removed = self.connection.execute(
            "DELETE FROM cache WHERE key LIKE '%:graph:%' AND rowid NOT IN "
            "(SELECT rowid FROM cache WHERE key LIKE '%:graph:%' ORDER BY rowid DESC LIMIT 8)"
        ).rowcount
        removed += self.connection.execute(
            "DELETE FROM cache WHERE key LIKE '%:blob:%' AND rowid NOT IN "
            "(SELECT rowid FROM cache WHERE key LIKE '%:blob:%' ORDER BY rowid DESC LIMIT 10000)"
        ).rowcount
        self.connection.commit()
        if removed:
            self.connection.execute("VACUUM")
        self.connection.close()

    def get(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value, digest FROM cache WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        value, digest = row
        return value if hashlib.sha256(value.encode()).hexdigest() == digest else None

    def put(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
            (key, value, hashlib.sha256(value.encode()).hexdigest()),
        )

    def parse_python(self, repo: Path, files: dict[str, str]) -> dict[str, ParsedSource]:
        """
        Parse every Python blob in ``files``, reusing checksummed records keyed by blob ID.

        The single parsing path for every repository the selector reads, consumer and first-party
        package alike, so both share one cache, one key scheme and one ``parsed_blobs`` count.
        """
        prefix = _cache_prefix()
        parsed: dict[str, ParsedSource] = {}
        missing: set[str] = set()
        for path, oid in files.items():
            if not path.endswith(".py"):
                continue
            raw = self.get(f"{prefix}blob:{oid}")
            if raw is not None:
                try:
                    parsed[oid] = ParsedSource.model_validate_json(raw)
                    continue
                except ValueError:
                    pass
            missing.add(oid)
        for oid, source in blobs(repo, missing).items():
            parsed[oid] = parse_source(source)
            self.put(f"{prefix}blob:{oid}", parsed[oid].model_dump_json())
            self.parsed_blobs += 1
        return parsed

    def snapshot(self, repo: Path, revision: str, config: ImpactConfig) -> Snapshot:
        git_tree = inventory(repo, revision)
        tree, files = git_tree.tree, git_tree.files
        # Exemptions change no edge; editing them must not discard the resolved graph.
        signature = hashlib.sha256(
            config.model_dump_json(
                exclude={"audit_exemptions", "floor_budget", "name_scoped_modules", "global_inputs"}
            ).encode()
        ).hexdigest()
        prefix = _cache_prefix()
        key = f"{prefix}graph:{tree}:{signature}"
        cached = self.get(key)
        if cached is not None:
            try:
                snapshot = Snapshot.model_validate_json(cached)
                if snapshot.tree == tree and snapshot.files == files:
                    self.snapshot_hits += 1
                    return snapshot
            except ValueError:
                pass
        parsed = self.parse_python(repo, files)
        deferred = deferred_routes(repo, tree, files, config)
        snapshot = resolve_graph(tree, files, parsed, config, git_tree.links, deferred)
        add_sidecar_edges(repo, tree, files, snapshot)
        # Declaration errors are actionable authoring failures, even when the
        # same tree also needs a collection-policy review/full-suite fallback.
        if policy_fingerprints(repo, git_tree, tuple(config.pytest_config_files)) != config.pytest_policy:
            raise ValueError("pytest configuration changed; review collection policy and refresh its fingerprints")
        self.put(key, snapshot.model_dump_json())
        self.connection.commit()
        return snapshot


def _single_assignment(tree: ast.Module, assignment: str) -> ast.expr | None:
    """The value of the module's one top-level assignment to `assignment`, if it is assigned exactly once."""
    statements = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == assignment
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    writes = sum(
        isinstance(node, ast.Name) and node.id == assignment and isinstance(node.ctx, ast.Store)
        for node in ast.walk(tree)
    )
    return statements[0].value if len(statements) == 1 and writes == 1 else None


def assignment_strings(source: bytes, assignment: str, deferred: frozenset[str] = frozenset()) -> set[str] | None:
    """
    Module names that occur only inside the file's single top-level assignment to `assignment`.

    None when the file doesn't parse, when the name is assigned anywhere other than exactly once at
    the top level (a computed or reassigned value can't be read without running the file), or when
    the assignment names no modules. A name that also occurs elsewhere in the file stays an
    ordinary edge, so the result can be empty. Elsewhere excludes the file's other `deferred`
    assignments: a task both routed and scheduled is deferred by both rules, not kept by each
    because the other holds it.
    """
    try:
        tree = parse_ast(source)
    except (SyntaxError, ValueError):
        return None
    value = _single_assignment(tree, assignment)
    if value is None:
        return None
    inside = {id(node) for node in ast.walk(value)}
    siblings = (_single_assignment(tree, other) for other in deferred - {assignment})
    held = {id(node) for sibling in siblings if sibling is not None for node in ast.walk(sibling)}
    found: set[str] = set()
    elsewhere: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and is_module_string(node.value):
            if id(node) in inside:
                found.add(node.value)
            elif id(node) not in held:
                elsewhere.add(node.value)
    return found - elsewhere if found else None


def deferred_routes(repo: Path, tree: str, files: dict[str, str], config: ImpactConfig) -> list[DeferredRoute]:
    """Resolve each `DeferredStringsRule` against one tree, failing on a rule it can't honor."""
    if not config.deferred_strings:
        return []
    python_files = {path for path in files if path.endswith(".py")}
    marked = {marker for rule in config.deferred_strings for marker in rule.consumer_markers}
    texts = (
        {path: text.decode("utf-8", "replace") for path, text in read_sources(repo, files, python_files).items()}
        if marked
        else {}
    )
    deferred: dict[str, frozenset[str]] = {}
    for rule in config.deferred_strings:
        deferred[rule.file] = deferred.get(rule.file, frozenset()) | set(rule.assignments)
    routes = []
    for rule in config.deferred_strings:
        location = f"{tree}:{rule.file}"
        oid = files.get(rule.file)
        source = blobs(repo, {oid})[oid] if oid and rule.file.endswith(".py") else None
        strings: set[str] = set()
        for assignment in rule.assignments:
            found = assignment_strings(source, assignment, deferred[rule.file]) if source is not None else None
            if found is None:
                raise DependencyDeclarationError(
                    f"{location}: deferred_strings needs one top-level {assignment} assignment naming modules"
                )
            strings |= found
        consumers: set[str] = set()
        for pattern in rule.consumers:
            consumers |= match_inputs(pattern, python_files, f"{location}:deferred_strings")
        undeclared = sorted(
            path
            for path, text in texts.items()
            if path not in consumers and path != rule.file and any(marker in text for marker in rule.consumer_markers)
        )
        if undeclared:
            raise DependencyDeclarationError(
                f"{location}: these files contain a consumer marker of {', '.join(rule.assignments)} but are not consumers: "
                + ", ".join(undeclared)
            )
        routes.append(DeferredRoute(file=rule.file, strings=sorted(strings), consumers=sorted(consumers)))
    return routes


def read_sources(repo: Path, files: dict[str, str], paths: set[str]) -> dict[str, bytes]:
    """The contents of ``paths``, read from the tree ``files`` describes."""
    contents = blobs(repo, {files[path] for path in paths})
    return {path: contents[files[path]] for path in paths}


def source_candidates(source: ParsedSource, package: str) -> set[str]:
    candidates: set[str] = set()
    for spec in source.imports:
        names = [ast.alias(name=name) for name in spec.names]
        node = (
            ast.Import(names=names)
            if not spec.module and not spec.level
            else ast.ImportFrom(module=spec.module, names=names, level=spec.level)
        )
        candidates.update(import_candidates(node, package))
    return candidates


class ModuleIndex:
    """Resolve against a complete Git inventory without filesystem probes."""

    def __init__(self, python_files: set[str], roots: list[str], links: list[str]) -> None:
        self.modules: dict[str, set[str]] = {}
        self.packages: dict[str, set[str]] = {}
        self.names: dict[str, set[str]] = {}
        for path in python_files:
            for root in roots:
                if not within(path, root):
                    continue
                relative = path if root == "." else path[len(root.rstrip("/")) + 1 :]
                parts = relative.removesuffix(".py").split("/")
                is_package = parts[-1] == "__init__"
                if is_package:
                    parts.pop()
                dotted = unicodedata.normalize("NFKC", ".".join(parts)).casefold()
                self.modules.setdefault(dotted, set()).add(path)
                package = dotted if is_package else dotted.rpartition(".")[0]
                self.packages.setdefault(path, set()).add(package)
                self.names.setdefault(path, set()).add(dotted)

        self.linked_modules = {
            unicodedata.normalize(
                "NFKC", (link if root == "." else link[len(root.rstrip("/")) + 1 :]).replace("/", ".")
            ).casefold()
            for link in links
            for root in roots
            if within(link, root)
        }

    def resolve(self, candidate: str) -> set[str]:
        # Union ambiguous roots/self.modules conservatively. Ancestor initializers
        # execute for every submodule import, even when never named explicitly.
        normalized = unicodedata.normalize("NFKC", candidate).casefold()
        if any(normalized == link or normalized.startswith(link + ".") for link in self.linked_modules):
            raise ValueError(f"import through unsupported Git symlink: {candidate}")
        result: set[str] = set()
        parts = unicodedata.normalize("NFKC", candidate).casefold().split(".")
        for end in range(1, len(parts) + 1):
            prefix = ".".join(parts[:end])
            result.update(self.modules.get(prefix, ()))
        return result


def resolve_graph(
    tree: str,
    files: dict[str, str],
    parsed: dict[str, ParsedSource],
    config: ImpactConfig,
    links: list[str],
    deferred: list[DeferredRoute] | None = None,
) -> Snapshot:
    python_files = {path for path in files if path.endswith(".py")}
    index = ModuleIndex(python_files, config.module_roots, links)

    edges: dict[str, set[str]] = {path: set() for path in files}
    unresolved: dict[str, list[str]] = {}
    opaque: dict[str, list[str]] = {}
    plugins: set[str] = set()
    tests = sorted(
        path
        for path in python_files
        if any(within(path, root) for root in config.test_roots)
        and matches(PurePosixPath(path).name, config.test_patterns)
    )
    deferred = deferred or []
    # Several rules may defer different assignments of one file; each file holds the union.
    held: dict[str, set[str]] = {}
    for route in deferred:
        held.setdefault(route.file, set()).update(route.strings)
    for path in python_files:
        source = parsed[files[path]]
        for comment in source.dependencies:
            edges[path].update(declared_inputs(comment, files, f"{tree}:{path}"))
        # A deferred name is not an edge of the file that only stores it; its consumers get it below.
        candidates = set(source.strings) - held.get(path, set())
        if source.django_urlconf and (config.django_urlconf is None or path != config.django_urlconf.settings_file):
            candidates.add(source.django_urlconf)
        for package in index.packages.get(path, {""}):
            candidates.update(source_candidates(source, package))
        for name in index.names.get(path, ()):
            edges[path].update(index.resolve(name))
        missing: list[str] = []
        for candidate in sorted(candidates):
            resolved = index.resolve(candidate)
            edges[path].update(resolved)
            if candidate not in index.modules:
                missing.append(candidate)
        if missing:
            unresolved[path] = missing
        if source.opaque:
            opaque[path] = source.opaque
        if (
            PurePosixPath(path).name == "conftest.py"
            and source.pytest_plugin
            and config.scoped_hooks.get(path) != files[path]
        ):
            plugins.add(path)
        edges[path].discard(path)

    for rule in config.dependencies:
        inputs = {path for path in files if matches(path, rule.inputs)}
        for reader in python_files:
            if matches(reader, rule.readers):
                edges[reader].update(
                    inputs - {reader} if rule.kind == "import" else {contents_node(path) for path in inputs}
                )
                # A reviewed declaration specifies all inputs of opaque reads.
                if rule.reviewed_readers.get(reader) == files[reader] and not any(
                    reason.startswith("cannot parse:") for reason in opaque.get(reader, [])
                ):
                    opaque.pop(reader, None)

    if policy := config.django_urlconf:
        settings_source = parsed.get(files.get(policy.settings_file, ""))
        module = settings_source.django_urlconf if settings_source else None
        if module is None or module.casefold() not in index.modules:
            raise DependencyDeclarationError(
                f"{tree}:{policy.settings_file}: ROOT_URLCONF must be one literal assignment to a tracked module"
            )
        # Reattach the deferred routes to every declared HTTP consumer and startup
        # check. Explicit imports/declarations above remain untouched.
        for pattern in policy.http_tests + policy.startup_tests:
            for test in match_inputs(pattern, set(tests), f"{tree}:django_urlconf"):
                edges[test].update(index.resolve(module))

    for route in deferred:
        targets = set().union(*(index.resolve(name) for name in route.strings))
        for consumer in route.consumers:
            edges[consumer].update(targets - {consumer})

    conftests = {path for path in python_files if PurePosixPath(path).name == "conftest.py"}
    globals_set = plugins | global_module_files(index, config)
    # Registration affects the whole session, including when a test module
    # loads the plugin. Follow nested declarations and retain the owner so
    # removing/changing its registration also invalidates every test.
    pending = list(conftests | set(tests) | globals_set)
    visited: set[str] = set()
    while pending:
        owner = pending.pop()
        if owner in visited:
            continue
        visited.add(owner)
        declared = parsed[files[owner]].registered_plugins
        if declared is None:
            raise ValueError(f"{owner}: cannot statically resolve pytest_plugins; run the full suite")
        if declared:
            globals_set.add(owner)
            for name in declared:
                targets = index.resolve(name)
                edges[owner].update(targets - {owner})
                if name not in index.modules:
                    unresolved[owner] = sorted(set(unresolved.get(owner, [])) | {name})
                pending.extend(targets)
    for test in tests:
        edges[test].update(globals_set - {test})
        for conftest in conftests:
            parent = str(PurePosixPath(conftest).parent)
            if within(test, parent):
                edges[test].add(conftest)
    return Snapshot(
        plugin_tests=sorted(globals_set & set(tests)),
        tree=tree,
        files=files,
        edges={path: sorted(deps) for path, deps in edges.items() if deps},
        tests=tests,
        opaque=opaque,
        unresolved=unresolved,
    )


def changed_paths(before: Snapshot, after: Snapshot) -> list[str]:
    """Paths whose blob differs between two trees, including additions and deletions."""
    return sorted(
        path for path in before.files.keys() | after.files.keys() if before.files.get(path) != after.files.get(path)
    )


def union_edges(*snapshots: Snapshot) -> dict[str, list[str]]:
    """
    Every tree's dependency edges, for traversal.

    Removed imports, deleted files and renamed modules must keep their former dependents.
    """
    edges: dict[str, set[str]] = {}
    for snapshot in snapshots:
        for path, deps in snapshot.edges.items():
            edges.setdefault(path, set()).update(deps)
    return {path: sorted(deps) for path, deps in edges.items()}


def seed_nodes(paths: list[str]) -> set[str]:
    """Graph nodes a changed path stands for: the file itself and readers of its contents."""
    return set(paths) | {contents_node(path) for path in paths}


def global_module_files(index: ModuleIndex, config: ImpactConfig) -> set[str]:
    """Files every test depends on because the configuration names them as startup modules."""
    files: set[str] = set()
    for module in config.global_modules:
        files |= index.resolve(module)
    return files


def reachable(edges: dict[str, list[str]], starts: set[str]) -> set[str]:
    seen = set(starts)
    queue = deque(starts)
    while queue:
        for target in edges.get(queue.popleft(), ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def reverse_edges(edges: dict[str, list[str]]) -> dict[str, list[str]]:
    reverse: dict[str, list[str]] = {}
    for reader, targets in edges.items():
        for target in targets:
            reverse.setdefault(target, []).append(reader)
    return reverse


def shortest_path(edges: dict[str, list[str]], starts: list[str], goals: set[str]) -> list[str]:
    """The shortest dependency path from any start to any goal node, reader first; empty if none."""
    parents: dict[str, str | None] = dict.fromkeys(starts)
    queue = deque(parents)
    while queue:
        node = queue.popleft()
        if node in goals:
            path = [node]
            while (parent := parents[path[-1]]) is not None:
                path.append(parent)
            return path[::-1]
        for target in edges.get(node, ()):
            if target not in parents:
                parents[target] = node
                queue.append(target)
    return []


def explanation(snapshot: Snapshot, test: str, source: str) -> list[str]:
    return [file_of(node) for node in shortest_path(snapshot.edges, [test], seed_nodes([source]))]


class EdgeEvidence:
    """
    Why one edge of a snapshot exists, re-read from the reader's source only for reported paths.

    The rules and their order are `resolve_graph`'s: import statements, then module strings
    (`is_module_string`), then the reader's own package initializers; a test's ancestor conftest,
    then startup modules and plugin conftests; anything else came from a declaration.
    """

    def __init__(self, repo: Path, snapshot: Snapshot, config: ImpactConfig) -> None:
        self.repo = repo
        self.snapshot = snapshot
        python_files = {path for path in snapshot.files if path.endswith(".py")}
        self.index = ModuleIndex(python_files, config.module_roots, inventory(repo, snapshot.tree).links)
        self.globals = global_module_files(self.index, config)
        self.tests = set(snapshot.tests)

    def _names(self, candidates: set[str], dependency: str) -> bool:
        return any(dependency in self.index.resolve(candidate) for candidate in candidates)

    def _line(self, reader: str, dependency: str) -> PathStep | None:
        oid = self.snapshot.files.get(reader)
        if not reader.endswith(".py") or not oid:
            return None
        tree = parse_ast(blobs(self.repo, {oid})[oid])
        packages = self.index.packages.get(reader, {""})
        # The first line in the file, when several create the same edge.
        imports = [
            node.lineno
            for node in iter_imports(tree)
            if any(self._names(import_candidates(node, package), dependency) for package in packages)
        ]
        if imports:
            return PathStep(path=reader, kind="import", line=min(imports))
        strings = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and is_module_string(node.value)
            and self._names({node.value}, dependency)
        ]
        return PathStep(path=reader, kind="string", line=min(strings)) if strings else None

    def step(self, reader: str, dependency: str) -> PathStep:
        dependency = file_of(dependency)
        if found := self._line(reader, dependency):
            return found
        kind: EdgeKind = "declared"
        if self._names(self.index.names.get(reader, set()), dependency):
            kind = "package"
        elif reader in self.tests and PurePosixPath(dependency).name == "conftest.py":
            # An ancestor supplies fixtures to its descendants; any other conftest is a global plugin.
            kind = "conftest" if within(reader, str(PurePosixPath(dependency).parent)) else "startup"
        elif reader in self.tests and dependency in self.globals:
            kind = "startup"
        return PathStep(path=reader, kind=kind)

    def path(self, nodes: list[str]) -> list[PathStep]:
        """Each step of a reader-first path, and the file it ends at."""
        files = [file_of(node) for node in nodes]
        return [self.step(reader, dependency) for reader, dependency in zip(files, files[1:])] + (
            [PathStep(path=files[-1])] if files else []
        )
