#!/usr/bin/env python3
"""
Require local explanations for changes that expand global pytest infrastructure.

The baseline is Git, not a checked-in symbol inventory. This stdlib-only command
runs before test selection. It parses source without importing application code.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

ACTIVATION = "# gv:test-requires-expansion-reason"
MARKER = "# pytest-global:"
SCOPES = {"function": 0, "class": 1, "module": 2, "package": 3, "session": 4}
DeclarationKey = tuple[str, str]
PYTHON_SOURCES = "*.py"
# Declarations named by module path; a move renames them without adding anything.
MODULE_DECLARATIONS = {"project-import", "plugin"}


@dataclass(frozen=True)
class Declaration:
    kind: str
    name: str
    line: int
    reason: str
    scope: str = "function"
    autouse: str = "False"
    body: str = ""


@dataclass
class Surface:
    declarations: dict[DeclarationKey, Declaration]
    imports: set[str]


# Git hands every hook the repository it is committing in through these variables, and a pre-commit
# hook inherits them. They are NOT overridden by `-C <root>`: GIT_DIR wins, so
# `GIT_DIR=other/.git git -C root log` reports `other`'s history while looking like it asked for
# `root`. Committing from a linked worktree (the only case where git exports GIT_DIR) therefore had
# this command diffing the wrong repository. Stripping them is what makes `-C` authoritative.
GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
    "GIT_QUARANTINE_PATH",
    "GIT_INDEX_VERSION",
)


def git_environment() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in GIT_LOCATION_ENV}


def git(root: Path, *args: str, index: Path | None = None) -> str:
    environment = git_environment()
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    # encoding is explicit because `text=True` alone decodes with the locale default, which is
    # cp1252 on Windows and raises UnicodeDecodeError on any UTF-8 source byte it has no mapping
    # for (0x8d among them).
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    if result.returncode:
        raise ValueError(f"Git history unavailable; fetch the requested base/head and retry: {result.stderr.strip()}")
    return result.stdout


@dataclass
class SourceTree:
    root: Path
    revision: str | None
    paths: set[str]
    module_roots: tuple[str, ...]

    def read(self, path: str) -> str:
        if path not in self.paths:
            return ""
        if self.revision is None:
            # Python source is UTF-8 by default (PEP 3120); reading it with the locale default
            # instead crashes the hook on Windows, where cp1252 has no mapping for byte 0x8d.
            return (self.root / path).read_text(encoding="utf-8")
        return git(self.root, "show", f"{self.revision}:{path}")

    # `paths` are Git's names, always forward-slashed, so path arithmetic on them is POSIX on every
    # OS. A native `Path` is a WindowsPath there: it joined `root / suffix` with backslashes, no
    # candidate ever matched `paths`, and the guard silently followed no import on Windows.
    def module_path(self, module: str) -> str | None:
        relative = module.replace(".", "/")
        candidates = (
            str(PurePosixPath(root) / suffix)
            for root in self.module_roots
            for suffix in (relative + ".py", relative + "/__init__.py")
        )
        return next((candidate for candidate in candidates if candidate in self.paths), None)

    def package(self, path: str) -> list[str]:
        for root in self.module_roots:
            try:
                relative = PurePosixPath(path).relative_to(root)
            except ValueError:
                continue
            # Both foo.py and package/__init__.py resolve relative imports
            # from their containing package, after removing the source root.
            return list(relative.parent.parts)
        return list(PurePosixPath(path).parent.parts)

    def module_name(self, path: str) -> str | None:
        """Invert `module_path`: `pkg/__init__.py` is `pkg`, so `from pkg import Name` maps too."""
        source = PurePosixPath(path)
        if source.suffix != ".py":
            return None
        parts = [*self.package(path), source.stem]
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts) or None


def protected(source: str) -> bool:
    """Only a real file-level comment activates enforcement, never prose in a string."""
    return any(
        token.type == tokenize.COMMENT and token.start[1] == 0 and token.string.strip() == ACTIVATION
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
    )


def within(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def reason_before(lines: list[str], line: int) -> str:
    for text in reversed(lines[: line - 1]):
        comment = text.strip()
        if not comment.startswith("#"):
            break
        if comment.startswith(MARKER):
            return comment.removeprefix(MARKER).strip()
    return ""


def module_nodes(node: ast.AST) -> list[ast.AST]:
    """Include conditional module declarations, but not function/class internals."""
    nodes: list[ast.AST] = []
    for child in ast.iter_child_nodes(node):
        nodes.append(child)
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes.extend(module_nodes(child))
    return nodes


def inspect_source(tree: SourceTree, path: str, project_prefixes: tuple[str, ...]) -> Surface:
    source = tree.read(path)
    parsed = ast.parse(source, filename=path)
    lines = source.splitlines()
    surface = Surface({}, set())
    aliases: dict[str, str] = {}

    def add(kind: str, name: str, node: ast.stmt, **fixture: str) -> None:
        line = node.lineno
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            line = min([line, *(item.lineno for item in node.decorator_list)])
        surface.declarations[(kind, name)] = Declaration(kind, name, line, reason_before(lines, line), **fixture)

    # Includes function-local imports: moving an application import into a
    # global fixture does not remove the fixture's dependency.
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
            modules = imports
            aliases.update((alias.asname or alias.name, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            package = tree.package(path)
            parent = ".".join(package[: len(package) - node.level + 1]) if node.level else ""
            module = ".".join(part for part in (parent, node.module) if part)
            imports = [f"{module}.{alias.name}" for alias in node.names]
            modules = [name if tree.module_path(name) else module for name in imports]
            aliases.update((alias.asname or alias.name, f"{module}.{alias.name}") for alias in node.names)
        else:
            continue
        surface.imports.update(modules)
        for imported in imports:
            if within(imported, project_prefixes):
                add("project-import", imported, node)

    for node in module_nodes(parsed):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("pytest_"):
                add("hook", node.name, node)
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                name = ast.unparse(call.func if call else decorator)
                first, *rest = name.split(".")
                resolved = ".".join([aliases.get(first, first), *rest])
                if resolved not in {"pytest.fixture", "pytest_asyncio.fixture"}:
                    continue
                options = {item.arg: item.value for item in call.keywords} if call else {}
                scope = (
                    ast.literal_eval(options["scope"])
                    if isinstance(options.get("scope"), ast.Constant)
                    else ast.unparse(options["scope"])
                    if "scope" in options
                    else "function"
                )
                exported = options.get("name")
                fixture_name = (
                    exported.value
                    if isinstance(exported, ast.Constant) and isinstance(exported.value, str)
                    else node.name
                )
                add(
                    "fixture",
                    fixture_name,
                    node,
                    scope=str(scope),
                    autouse=ast.unparse(options["autouse"]) if "autouse" in options else "False",
                    body=ast.dump(node.args) + ast.dump(ast.Module(body=node.body, type_ignores=[])),
                )
        elif isinstance(node, ast.ClassDef):
            add("class", node.name, node, body=ast.dump(ast.Module(body=node.body, type_ignores=[])))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr)):
            if isinstance(node, ast.Expr):
                call = node.value
                if not isinstance(call, ast.Call) or ast.unparse(call.func) not in {
                    "pytest_plugins.append",
                    "pytest_plugins.extend",
                }:
                    continue
                value_node = call.args[0] if len(call.args) == 1 else call
            else:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if not any(isinstance(target, ast.Name) and target.id == "pytest_plugins" for target in targets):
                    continue
                value_node = node.value
            try:
                value = ast.literal_eval(value_node) if value_node else []
            except (ValueError, TypeError):
                value = None
            plugins = [value] if isinstance(value, str) else value
            if isinstance(plugins, (list, tuple)) and all(isinstance(item, str) for item in plugins):
                for plugin in plugins:
                    add("plugin", plugin, node)
                    surface.imports.add(plugin)
            else:
                add("plugin", "dynamic registration: " + ast.unparse(node), node)
    return surface


def surfaces(
    tree: SourceTree, path: str, project_prefixes: tuple[str, ...], follow_prefixes: tuple[str, ...]
) -> dict[str, Surface]:
    result: dict[str, Surface] = {}
    pending = [path]
    while pending:
        current = pending.pop()
        if current in result or current not in tree.paths:
            continue
        surface = inspect_source(tree, current, project_prefixes)
        result[current] = surface
        for module in surface.imports:
            if within(module, follow_prefixes):
                dependency = tree.module_path(module)
                if dependency:
                    pending.append(dependency)
    return result


Expansion = tuple[Declaration, str]
LocatedDeclaration = tuple[str, DeclarationKey]


def expansions(before: Surface, after: Surface) -> list[Expansion]:
    result: list[Expansion] = []
    removed = {key: entry for key, entry in before.declarations.items() if key not in after.declarations}
    for key, entry in after.declarations.items():
        previous = before.declarations.get(key)
        if previous is None and entry.kind in {"fixture", "class"}:
            # A pure rename does not grow the global surface. Consume each old
            # declaration once so copying a fixture still counts as an addition.
            renamed = next(
                (old_key for old_key, old in removed.items() if old.kind == entry.kind and old.body == entry.body), None
            )
            if renamed:
                previous = removed.pop(renamed)
        if previous is None:
            result.append((entry, ""))
        elif entry.kind == "fixture":
            wider_scope = entry.scope != previous.scope and (
                entry.scope not in SCOPES
                or previous.scope not in SCOPES
                or SCOPES[entry.scope] > SCOPES[previous.scope]
            )
            wider_autouse = entry.autouse != previous.autouse and entry.autouse != "False"
            if wider_scope or wider_autouse:
                result.append((entry, previous.reason))
    return result


def worktree_snapshot(root: Path) -> str:
    """
    Record the working tree's Python sources as a tree object without touching the real index.

    Rename detection needs both sides in Git, but the local check also sees unstaged and untracked
    edits. Staging into a copy of the index keeps its stat cache, so only changed files are hashed.
    """
    real_index = root / git(root, "rev-parse", "--git-path", "index").strip()
    with tempfile.TemporaryDirectory() as scratch:
        index = Path(scratch) / "index"
        if real_index.is_file():
            shutil.copyfile(real_index, index)
        git(root, "add", "--all", "--", PYTHON_SOURCES, index=index)
        return git(root, "write-tree", index=index).strip()


def moved_packages(paths: dict[str, str], before: SourceTree, after: SourceTree) -> list[tuple[str | None, str | None]]:
    """
    Packages whose modules all moved to one directory, which the package itself left.

    `from pkg import Name` names the package, and an empty `__init__.py` has no content for Git to
    match. A directory that still has Python files at head, or whose files scattered, keeps its name.
    """
    destinations: dict[str, set[str]] = {}
    for source, target in paths.items():
        old, new = PurePosixPath(source), PurePosixPath(target)
        if old.name == new.name:
            destinations.setdefault(str(old.parent), set()).add(str(new.parent))
    remaining = {str(PurePosixPath(path).parent) for path in after.paths if path.endswith(".py")}
    return [
        (before.module_name(f"{directory}/__init__.py"), after.module_name(f"{target}/__init__.py"))
        for directory, targets in destinations.items()
        if len(targets) == 1 and directory not in remaining
        for target in targets
    ]


@dataclass(frozen=True)
class Renames:
    """
    Git's rename detection between the baseline and head, applied to the baseline's surfaces.

    Moving a module does not grow the global surface: its declarations, their reasons, and the
    imports naming it move together. Carrying the baseline to head paths and module names lets
    `expansions` compare like with like; a copy keeps its source, so Git reports it as added.
    """

    paths: dict[str, str]
    # Longest first, so a moved module inside a moved package takes its own destination.
    modules: tuple[tuple[str, str], ...]

    @classmethod
    def between(cls, before: SourceTree, after: SourceTree, baseline: str, head_tree: str) -> Renames:
        # Every empty file is the same blob, so Git would pair unrelated empty `__init__.py` files.
        fields = git(
            before.root,
            "diff",
            "-z",
            "--name-status",
            "-M50%",
            "-l0",
            "--no-rename-empty",
            baseline,
            head_tree,
            "--",
            PYTHON_SOURCES,
        ).split("\0")
        # `-z` rows are `status, path` or, for a rename, `status, old, new`; no `-C`, so no copies.
        paths: dict[str, str] = {}
        rows = iter(fields)
        for status in rows:
            source = next(rows, "")
            if status.startswith("R"):
                paths[source] = next(rows)
        pairs = [(before.module_name(source), after.module_name(target)) for source, target in paths.items()]
        pairs += moved_packages(paths, before, after)
        modules = {old: new for old, new in pairs if old and new and old != new}
        return cls(paths, tuple(sorted(modules.items(), key=lambda item: len(item[0]), reverse=True)))

    def origin(self, path: str) -> str:
        return next((old for old, new in self.paths.items() if new == path), path)

    def module(self, name: str) -> str:
        for old, new in self.modules:
            if within(name, (old,)):
                return new + name.removeprefix(old)
        return name

    def carry(self, baseline: dict[str, Surface]) -> dict[str, Surface]:
        carried: dict[str, Surface] = {}
        for path, surface in baseline.items():
            declarations = [
                replace(entry, name=self.module(entry.name)) if entry.kind in MODULE_DECLARATIONS else entry
                for entry in surface.declarations.values()
            ]
            carried[self.paths.get(path, path)] = Surface(
                {(entry.kind, entry.name): entry for entry in declarations}, surface.imports
            )
        return carried


def check(
    root: Path,
    base: str,
    head: str | None,
    *,
    module_roots: tuple[str, ...],
    project_prefixes: tuple[str, ...],
    follow_prefixes: tuple[str, ...],
) -> int:
    baseline = git(root, "merge-base", base, head or "HEAD").strip()
    before = SourceTree(
        root, baseline, set(git(root, "ls-tree", "-r", "--name-only", baseline).splitlines()), module_roots
    )
    if head:
        revision = git(root, "rev-parse", "--verify", head + "^{commit}").strip()
        after = SourceTree(
            root, revision, set(git(root, "ls-tree", "-r", "--name-only", revision).splitlines()), module_roots
        )
        head_tree = revision
    else:
        paths = set(git(root, "ls-files", "--cached", "--others", "--exclude-standard").splitlines())
        after = SourceTree(root, None, {path for path in paths if (root / path).is_file()}, module_roots)
        head_tree = worktree_snapshot(root)
    renames = Renames.between(before, after, baseline, head_tree)
    failed = False
    seen: set[LocatedDeclaration] = set()
    # A conftest deleted by this diff loads nothing, so only head conftests can expand.
    for path in sorted(after.paths):
        if PurePosixPath(path).name != "conftest.py":
            continue
        origin = renames.origin(path)
        # Keep base activation for the whole PR: deleting the comment cannot
        # excuse an expansion in a later commit of that same PR.
        if not (protected(before.read(origin)) or protected(after.read(path))):
            continue
        # A conftest's directory is its scope. Moved anywhere but within that directory it reaches
        # tests it never loaded for, so nothing it loads, however old, has a baseline there.
        old_surfaces = (
            renames.carry(surfaces(before, origin, project_prefixes, follow_prefixes))
            if PurePosixPath(path).parent.is_relative_to(PurePosixPath(origin).parent)
            else {}
        )
        for relative, surface in surfaces(after, path, project_prefixes, follow_prefixes).items():
            for entry, previous_reason in expansions(old_surfaces.get(relative, Surface({}, set())), surface):
                identity = (relative, (entry.kind, entry.name))
                if identity in seen:
                    continue
                seen.add(identity)
                location = f"{relative}:{entry.line}: {entry.kind} {entry.name}"
                if entry.reason and entry.reason != previous_reason:
                    print(f"EXPLAINED {location}: {entry.reason}")
                else:
                    failed = True
                    print(
                        f"BLOCKED {location}: use the narrowest consuming conftest or explicit harness; if global scope is required, add a fresh '{MARKER} <why local scope does not fit>' immediately above this declaration. Activated by {ACTIVATION} in {path}"
                    )
    if not seen:
        print("No global pytest expansion; ordinary maintenance needs no policy update.")
    return int(failed)


def main() -> int:
    # The report echoes reasons and declaration names straight out of source comments, which
    # routinely carry non-ASCII punctuation. Encoding those to a cp1252 console raises
    # UnicodeEncodeError and buries the findings under a traceback; degrade the characters instead.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--base", default="HEAD", help="Compare from the merge base of this ref and head (default: HEAD)."
    )
    parser.add_argument("--head", help="Committed head; omit to inspect local edits, as pre-commit does.")
    parser.add_argument(
        "--module-root", action="append", help="Python source root; repeat for src and repository layouts. Default: ."
    )
    parser.add_argument(
        "--project-import-prefix",
        action="append",
        required=True,
        help="Application/test module prefix whose additions need a reason; repeat as needed.",
    )
    parser.add_argument(
        "--follow-import-prefix",
        action="append",
        default=[],
        help="Loaded helper/plugin prefix to check transitively; repeat as needed.",
    )
    args = parser.parse_args()
    try:
        return check(
            args.repo,
            args.base,
            args.head,
            module_roots=tuple(args.module_root or ["."]),
            project_prefixes=tuple(args.project_import_prefix),
            follow_prefixes=tuple(args.follow_import_prefix),
        )
    except (OSError, ValueError, SyntaxError, tokenize.TokenError) as error:
        print(f"Global pytest editing check: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
