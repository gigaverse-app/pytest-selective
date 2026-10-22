"""
Narrow a change to a name-scoped module to the files that read the names it changes.

Some modules are read name by name: a settings module, a constants module, a feature-flag table. Every
importer depends on the whole file, so an edit to one value selects every test that loads it, which is
every test when the module is global. A `NameScopedModule` declares that its readers depend only on the
names they read. A change that only rebinds names then selects the files that read those names; anything
the selector cannot prove keeps the module's ordinary edges.

Design and limits: docs/technical-design/test-impact.md#name-scoped-modules.
"""

import ast
import difflib
import fnmatch
import io
import re
import tokenize
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pytest_selective.ast_imports import import_candidates, iter_imports
from pytest_selective.impact_declarations import SIDECAR_SUFFIX, match_inputs
from pytest_selective.impact_graph import (
    ModuleIndex,
    blobs,
    contents_node,
    inventory,
    matches,
    reachable,
    read_sources,
    reverse_edges,
    seed_nodes,
    union_edges,
)
from pytest_selective.impact_models import ImpactConfig, NameScopedModule, Snapshot

#: Methods that change the name they are called on, as a statement (``SCHEDULE.update({...})``).
_MUTATORS = frozenset({"append", "extend", "insert", "update", "setdefault", "add"})
#: A maximal run of ASCII word characters: exactly the spans ``\b...\b`` delimits in bytes.
_WORD_RUN = re.compile(rb"[A-Za-z0-9_]+")

StatementKind = Literal["binding", "function", "code", "inert"]


class NotNarrowed(Exception):
    """The change cannot be proven to reach only the readers of the names it changes."""


@dataclass(frozen=True)
class _Statement:
    kind: StatementKind
    binds: frozenset[str]
    reads: frozenset[str]
    calls: tuple[str, ...]
    line: int
    dump: str


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a name or attribute chain, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _root(node: ast.expr) -> str | None:
    """The name a subscript or attribute target ultimately writes into."""
    while isinstance(node, (ast.Attribute, ast.Subscript, ast.Starred)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _target_names(target: ast.expr) -> set[str]:
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for element in target.elts for name in _target_names(element)}
    root = _root(target)
    return {root} if root else set()


def _loads(node: ast.AST) -> frozenset[str]:
    return frozenset(n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))


def _callee(node: ast.expr) -> str:
    """
    A callee as written: ``config.str``, or ``config.str().lower`` for a method of a call's result.

    ``?`` for anything else (a subscript, a lambda), which no ``pure_calls`` pattern but ``*`` matches.
    """
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Call):
            return f"{_callee(node.value.func)}().{node.attr}"
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else f"?.{node.attr}"
    return _dotted(node) or "?"


def _calls(node: ast.AST) -> tuple[str, ...]:
    """Every call's callee, as `_callee` writes it."""
    return tuple(_callee(n.func) for n in ast.walk(node) if isinstance(n, ast.Call))


def _statement(node: ast.stmt) -> _Statement:
    dump = ast.dump(node)
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        return _Statement("inert", frozenset(), frozenset(), (), node.lineno, dump)
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        binds = frozenset(name for target in targets for name in _target_names(target))
        value = node.value
        reads = _loads(value) if value is not None else frozenset()
        # A subscript target's key is read too: SCHEDULE[KEY] = ...
        reads |= frozenset(name for target in targets for name in _loads(target) if name not in binds)
        return _Statement("binding", binds, reads, _calls(value) if value else (), node.lineno, dump)
    if (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr in _MUTATORS
        and (root := _root(node.value.func.value))
    ):
        arguments = [*node.value.args, *(keyword.value for keyword in node.value.keywords)]
        reads = frozenset(name for argument in arguments for name in _loads(argument))
        calls = tuple(callee for argument in arguments for callee in _calls(argument))
        return _Statement("binding", frozenset({root}), reads, calls, node.lineno, dump)
    # A decorator runs when the module loads and can hand the function to a framework that calls it
    # without naming it (a signal receiver, a task, a route), so a decorated definition is code.
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.decorator_list:
        return _Statement("function", frozenset({node.name}), _loads(node), _calls(node), node.lineno, dump)
    return _Statement("code", frozenset(), _loads(node), _calls(node), node.lineno, dump)


def _statements(source: bytes, label: str) -> list[_Statement]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as error:
        raise NotNarrowed(f"{label} does not parse: {error}") from error
    statements = [_statement(node) for node in tree.body]
    # The module docstring is the module's __doc__, which a CLI's help text or a schema may read.
    if statements and statements[0].kind == "inert":
        statements[0] = _Statement(
            "binding", frozenset({"__doc__"}), frozenset(), (), statements[0].line, statements[0].dump
        )
    return statements


def _is_pure(
    callee: str,
    pure_calls: Iterable[str],
    functions: Mapping[str, _Statement],
    seen: frozenset[str] = frozenset(),
) -> bool:
    if any(fnmatch.fnmatchcase(callee, pattern) for pattern in pure_calls):
        return True
    function = functions.get(callee)
    if function is None or callee in seen:
        return callee in seen
    return all(_is_pure(inner, pure_calls, functions, seen | {callee}) for inner in function.calls)


def changed_names(before: bytes, after: bytes, module: NameScopedModule) -> set[str]:
    """
    The top-level names a change rebinds, directly or through what they are computed from.

    Raises ``NotNarrowed`` when the change does anything else: changes an import or any other statement
    that runs code, changes code that reads a changed name, or calls something ``module.pure_calls`` does
    not name while computing a changed name.
    """
    old, new = _statements(before, f"{module.file} (base)"), _statements(after, f"{module.file} (head)")
    # Order matters: moving `X = 2` above `X = 1` changes X. A statement outside the longest common
    # subsequence of the two versions is edited, including one that only moved.
    matcher = difflib.SequenceMatcher(None, [s.dump for s in old], [s.dump for s in new], autojunk=False)
    kept_old = {i for block in matcher.get_matching_blocks() for i in range(block.a, block.a + block.size)}
    kept_new = {j for block in matcher.get_matching_blocks() for j in range(block.b, block.b + block.size)}
    edited = [s for i, s in enumerate(old) if i not in kept_old] + [s for j, s in enumerate(new) if j not in kept_new]
    for statement in edited:
        if statement.kind == "code":
            raise NotNarrowed(f"{module.file}:{statement.line} changes a statement that runs code")
    names = {name for statement in edited for name in statement.binds}
    # Whatever is computed from a changed name changes with it, in either version of the file.
    everything = old + new
    while True:
        # Code that reads a changed name always counts; a binding counts until its names are in.
        dependents = [s for s in everything if s.reads & names and (s.kind == "code" or not s.binds <= names)]
        for statement in dependents:
            if statement.kind == "code":
                raise NotNarrowed(
                    f"{module.file}:{statement.line} runs code that reads " + ", ".join(sorted(statement.reads & names))
                )
        grown = names | {name for statement in dependents for name in statement.binds}
        if grown == names:
            break
        names = grown
    functions = {name: s for s in everything if s.kind == "function" for name in s.binds}
    for statement in everything:
        if statement.kind != "binding" or not statement.binds & names:
            continue
        for callee in statement.calls:
            if not _is_pure(callee, module.pure_calls, functions):
                raise NotNarrowed(
                    f"{module.file}:{statement.line} calls {callee} while computing "
                    + ", ".join(sorted(statement.binds & names))
                    + "; name it in pure_calls if it has no side effects"
                )
    return names


def externally_read(names: Iterable[str], module: NameScopedModule, routed: set[str]) -> set[str]:
    """Changed names code outside the repository reads, except those a deferred-strings rule routes."""
    return {
        name
        for name in names
        if name not in routed and (name in module.external_names or name.startswith(tuple(module.external_prefixes)))
    }


def _casefold(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold()


def _bindings(
    tree: ast.Module, packages: Iterable[str], accessors: Iterable[str], modules: Iterable[str]
) -> tuple[set[str], bool]:
    """
    Local names bound to an accessor or to the module, and whether the file reads names it can't name.

    ``modules`` are the module's dotted names, one per module root. Relative imports resolve against
    ``packages``, the importer's own. A star import of the module, or an unaliased ``import pkg.module``
    (whose attribute chains this does not follow), reads names the selector can't see.
    """
    wanted = {_casefold(name) for name in modules}
    accessor_names = {_casefold(name) for name in accessors}
    bound: set[str] = set()
    unnamed = False
    for node in iter_imports(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _casefold(alias.name) in wanted:
                    if alias.asname:
                        bound.add(alias.asname)
                    else:
                        unnamed = True
            continue
        for package in packages:
            bases = import_candidates(ast.ImportFrom(module=node.module, names=[], level=node.level), package)
            for base in bases:
                for alias in node.names:
                    if alias.name == "*":
                        unnamed = unnamed or _casefold(base) in wanted
                    elif _casefold(f"{base}.{alias.name}") in wanted | accessor_names:
                        bound.add(alias.asname or alias.name)
    return bound, unnamed


def _is_named_read(node: ast.Name, parent: ast.AST | None) -> bool:
    """``binding.NAME``, or ``getattr(binding, "NAME")`` / ``hasattr`` with a literal name."""
    if isinstance(parent, ast.Attribute) and parent.value is node:
        return parent.attr != "__dict__"
    return (
        isinstance(parent, ast.Call)
        and isinstance(parent.func, ast.Name)
        and parent.func.id in {"getattr", "hasattr"}
        and len(parent.args) > 1
        and parent.args[0] is node
        and isinstance(parent.args[1], ast.Constant)
        and isinstance(parent.args[1].value, str)
    )


def _may_bind(source: bytes, dotted_names: Iterable[str]) -> bool:
    """Whether ``source`` spells the last part of any of ``dotted_names``; only such a file can bind one."""
    lowered = source.lower()
    return any(name.rpartition(".")[2].lower().encode() in lowered for name in dotted_names)


def reads_unnamed(
    source: bytes, accessors: Iterable[str], modules: Iterable[str], packages: Iterable[str] = ("",)
) -> bool:
    """
    Whether a file reads names of the module without naming them, through an accessor or the module.

    ``binding.NAME`` and ``getattr(binding, "NAME")`` name what they read, which `named_readers` finds.
    Any other use of the binding reads names the selector can't see: ``getattr(binding, name)``,
    ``vars(binding)``, ``binding.__dict__``, passing the object on, ``importlib.reload(binding)``, which
    runs the whole module again, or ``from module import *``.
    """
    modules, accessors = list(modules), list(accessors)
    if not _may_bind(source, [*modules, *accessors]):
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError, ValueError:
        return True
    bound, unnamed = _bindings(tree, packages, accessors, modules)
    if unnamed:
        return True
    if not bound:
        return False
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    return any(
        isinstance(node, ast.Name)
        and node.id in bound
        and isinstance(node.ctx, ast.Load)
        and not _is_named_read(node, parents.get(node))
        for node in ast.walk(tree)
    )


def _code(source: bytes) -> bytes:
    """
    ``source`` without its comments and docstrings, which never run, as space-separated tokens.

    A file that does not tokenize or parse comes back whole, so its textual matches still count.
    """
    try:
        tree = ast.parse(source)
        tokens = list(tokenize.tokenize(io.BytesIO(source).readline))
    except SyntaxError, ValueError, tokenize.TokenError:
        return source
    docstrings = {
        (first.lineno, first.col_offset)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(first := node.body[0], ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    }
    return b" ".join(
        token.string.encode()
        for token in tokens
        if token.type != tokenize.COMMENT and not (token.type == tokenize.STRING and token.start in docstrings)
    )


def named_readers(sources: Mapping[str, bytes], names: Iterable[str], exclude: str) -> set[str]:
    """
    Files whose code mentions any of ``names`` as a whole word: attribute reads, imports, overrides, strings.

    A mention in a comment or a docstring reads nothing, so it does not count.
    """
    names = sorted(names)
    if not names:
        return set()
    pattern = re.compile(rb"\b(?:" + b"|".join(re.escape(name.encode()) for name in names) + rb")\b")
    return {
        path
        for path, source in sources.items()
        if path != exclude and pattern.search(source) and pattern.search(_code(source))
    }


def externally_read_names(module_source: bytes, roots: Iterable[Path], name_pattern: str = r".+") -> set[str]:
    """
    The top-level names the module binds that any Python file under ``roots`` mentions.

    Run it in the consumer's installed environment with its site-packages as ``roots``: the result is
    the names installed code may read, which ``NameScopedModule.external_names`` must list. Only names
    that fully match ``name_pattern`` count; Django reads only uppercase settings, for one, so its
    consumers pass ``[A-Z][A-Z0-9_]*``. It over-approximates on purpose: a name that only appears in a
    comment still counts.
    """
    accepted = re.compile(name_pattern)
    tree = ast.parse(module_source)
    names = {name for node in tree.body for name in _statement(node).binds if accepted.fullmatch(name)}
    if not names:
        return set()
    # A name "mentioned" is a whole ASCII word run (what ``\bNAME\b`` matches in bytes). Splitting each
    # file into word runs once and intersecting is ~25x faster over a site-packages than one alternation
    # of every name; only non-ASCII names, which a word run cannot contain, keep the alternation.
    ascii_names = {name.encode() for name in names if name.isascii()}
    others = sorted(name.encode() for name in names if not name.isascii())
    pattern = re.compile(rb"\b(" + b"|".join(map(re.escape, others)) + rb")\b") if others else None
    found: set[bytes] = set()
    for root in roots:
        for path in Path(root).rglob("*.py"):
            try:
                source = path.read_bytes()
            except OSError:
                continue
            found.update(ascii_names.intersection(_WORD_RUN.findall(source)))
            if pattern is not None:
                found.update(pattern.findall(source))
            if len(found) == len(names):
                return names
    return {name.decode() for name in found}


def _routed(config: ImpactConfig, module: NameScopedModule) -> dict[str, list[str]]:
    """Names of the module a deferred-strings rule routes, to that rule's consumer patterns."""
    routed: dict[str, list[str]] = {}
    for rule in config.deferred_strings:
        if rule.file == module.file:
            for assignment in rule.assignments:
                routed.setdefault(assignment, []).extend(rule.consumers)
    return routed


def _readers_of_every_name(
    repo: Path, snapshot: Snapshot, sources: Mapping[str, bytes], config: ImpactConfig, module: NameScopedModule
) -> set[str]:
    """
    Files that read the module other than name by name, so every change to it reaches them.

    That is a file that reads names without naming them (`reads_unnamed`), reads the file's contents, or
    declares the file by path, inline, in a sidecar or in a dependency rule. A string that names the
    module for a framework to load is not such a read; what the framework then reads is
    ``external_names``.
    """
    index = ModuleIndex(set(sources), config.module_roots, inventory(repo, snapshot.tree).links)
    modules = index.names.get(module.file, set())
    contents = contents_node(module.file)
    path = module.file.encode()
    readers = {reader for reader, dependencies in snapshot.edges.items() if contents in dependencies}
    for reader, source in sources.items():
        if reader == module.file:
            continue
        packages = index.packages.get(reader, {""})
        if path in source or reads_unnamed(source, module.accessors, modules, packages):
            readers.add(reader)
    sidecars = {test + SIDECAR_SUFFIX: test for test in snapshot.tests}
    sidecar_oids = {name: snapshot.files[name] for name in sidecars if name in snapshot.files}
    if sidecar_oids:
        texts = blobs(repo, set(sidecar_oids.values()))
        readers.update(sidecars[name] for name, oid in sidecar_oids.items() if path in texts[oid])
    files = list(snapshot.files)
    readers.update(
        reader
        for rule in config.dependencies
        if matches(module.file, rule.inputs)
        for reader in files
        if matches(reader, rule.readers)
    )
    return readers


@dataclass(frozen=True)
class Narrowed:
    """The files a proven change to a name-scoped module reaches, and why."""

    readers: set[str]
    reason: str


def narrow_name_scoped_change(
    repo: Path, snapshots: tuple[Snapshot, Snapshot], config: ImpactConfig, module: NameScopedModule
) -> Narrowed:
    """
    Replace a change to a name-scoped module with the files that read what it changed.

    Raises ``NotNarrowed`` with the reason whenever that cannot be proven; the caller then keeps the
    module's ordinary edges.
    """
    before, after = snapshots
    old_oid, new_oid = before.files.get(module.file), after.files.get(module.file)
    if not old_oid or not new_oid:
        raise NotNarrowed(f"{module.file} was added or removed")
    texts = blobs(repo, {old_oid, new_oid})
    names = changed_names(texts[old_oid], texts[new_oid], module)
    routed = _routed(config, module)
    external = externally_read(names, module, set(routed))
    if external:
        raise NotNarrowed("code outside the repository reads " + ", ".join(sorted(external)))
    # A file can read the module's names only by loading it, through imports or an accessor. Mentioning
    # a name without either is a coincidence, and selecting it would widen selection past the module's
    # own dependents, so named readers come only from those two.
    dependents = reachable(reverse_edges(union_edges(*snapshots)), seed_nodes([module.file]))
    readers: set[str] = set()
    for snapshot in snapshots:
        sources = read_sources(repo, snapshot.files, {path for path in snapshot.files if path.endswith(".py")})
        loaders = {
            path: source
            for path, source in sources.items()
            if path in dependents or _may_bind(source, module.accessors)
        }
        readers |= named_readers(loaders, names, exclude=module.file)
        readers |= _readers_of_every_name(repo, snapshot, sources, config, module)
        python_files = set(sources)
        for name in names & set(routed):
            for pattern in routed[name]:
                readers |= match_inputs(pattern, python_files, f"{snapshot.tree}:name_scoped_modules")
    readers.discard(module.file)
    for pattern in module.load_checks:
        readers |= match_inputs(pattern, set(after.tests), f"{after.tree}:name_scoped_modules.load_checks")
    changed = ", ".join(sorted(names)) if names else "nothing a test can observe"
    return Narrowed(
        readers=readers,
        reason=f"{module.file} narrowed: it changes {changed}; {len(readers)} files read those names",
    )
