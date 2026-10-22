"""
Characterize a first-party dependency pin move by the modules it actually changes.

Consumers declare their lock file and manifest as inputs of the root conftest: the whole pytest
invocation runs on that installed dependency set, so any change to it can affect any test. That is
right for third-party upgrades and far too broad for a package whose source this organization owns.
A backend-common pin moves on every push to a backend-common pull request and once more when it
merges, and each move re-ran every consumer test, including a post-merge repin between two commits
with byte-identical package contents.

For a declared first-party package this module proves the lock and manifest differ only in that
package's pin, fetches both pinned commits from the declared repository, and returns the dotted
names of the package modules that changed or import something that changed. Anything it cannot
prove raises ``ValueError``, and the caller keeps the lock and manifest as global inputs.
"""

import base64
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from pytest_selective.impact_graph import (
    GraphCache,
    inventory,
    pytest_policies,
    reachable,
    resolve_graph,
    reverse_edges,
    union_edges,
    within,
)
from pytest_selective.impact_models import FirstPartyPackage, ImpactConfig, ImpactModel

COMMIT_LENGTH = 40
#: Commits the cached clone may hold before it is rebuilt from the two a pin move needs.
MAX_CACHED_COMMITS = 16
#: Pin keys a uv source may use; a move between any of them is still only a pin move.
PIN_KEYS = ("rev", "tag", "branch")


class PinMove(ImpactModel):
    """The two commits a first-party pin moved between."""

    old: str
    new: str


class PackageChange(ImpactModel):
    """What a pin move changes inside the installed package."""

    #: Installed files that differ between the pinned commits. Empty means the installed
    #: environment is byte-identical, which is what lets lock-triggered lanes skip.
    installed_files: list[str]
    #: Dotted names of package modules that changed or import something that changed.
    modules: list[str]


def _toml(document: bytes, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(document.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot parse {label}: {error}") from error


def _base_url(source: str) -> str:
    return source.split("#", 1)[0].split("?", 1)[0]


def _normalize(value: Any, repository: str) -> Any:
    """Replace every reference to the first-party repository with the bare repository URL."""
    if isinstance(value, dict):
        return {key: _normalize(item, repository) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, repository) for item in value]
    if isinstance(value, str) and _base_url(value) == repository:
        return repository
    return value


def _locked_commit(document: dict[str, Any], spec: FirstPartyPackage, label: str) -> str:
    entries = [entry for entry in document.get("package", []) if entry.get("name") == spec.name]
    if len(entries) != 1:
        raise ValueError(f"{label} locks {len(entries)} entries named {spec.name}")
    source = entries[0].get("source", {}).get("git")
    if not isinstance(source, str):
        raise ValueError(f"{label} does not lock {spec.name} from git")
    if _base_url(source) != spec.repository:
        raise ValueError(f"{label} source {_base_url(source)} does not match the declared repository {spec.repository}")
    commit = source.partition("#")[2]
    if len(commit) != COMMIT_LENGTH or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError(f"{label} records no commit for {spec.name}")
    return commit


def _without_package(document: dict[str, Any], spec: FirstPartyPackage) -> dict[str, Any]:
    """
    Drop the package's own lock entry, which describes the package rather than the environment.

    Its version, dependency list and metadata follow its source; any consequence for the installed
    environment appears as a change to some other entry, which still counts.
    """
    stripped = dict(document)
    stripped["package"] = [entry for entry in document.get("package", []) if entry.get("name") != spec.name]
    return stripped


def _changed_entries(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    def by_name(document: dict[str, Any]) -> dict[str, Any]:
        return {entry.get("name", "?"): entry for entry in document.get("package", [])}

    old, new = by_name(before), by_name(after)
    changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    top = sorted(key for key in before.keys() | after.keys() if key != "package" and before.get(key) != after.get(key))
    return changed + top


def _unpinned_manifest(document: dict[str, Any], spec: FirstPartyPackage) -> dict[str, Any]:
    normalized = _normalize(document, spec.repository)
    source = normalized.get("tool", {}).get("uv", {}).get("sources", {}).get(spec.name)
    if isinstance(source, dict):
        for key in PIN_KEYS:
            source.pop(key, None)
    return normalized


def first_party_pin_move(
    spec: FirstPartyPackage,
    *,
    before_lock: bytes,
    after_lock: bytes,
    before_manifest: bytes | None,
    after_manifest: bytes | None,
) -> PinMove:
    """
    Prove the lock and manifest differ only in ``spec``'s pin, and name both commits.

    Raises ``ValueError`` describing whatever else changed, or why the pin cannot be read.
    """
    before, after = _toml(before_lock, spec.lock), _toml(after_lock, spec.lock)
    move = PinMove(
        old=_locked_commit(before, spec, f"base {spec.lock}"),
        new=_locked_commit(after, spec, f"head {spec.lock}"),
    )
    old_environment = _normalize(_without_package(before, spec), spec.repository)
    new_environment = _normalize(_without_package(after, spec), spec.repository)
    if old_environment != new_environment:
        raise ValueError(f"{spec.lock} also changes {', '.join(_changed_entries(old_environment, new_environment))}")
    if (before_manifest is None) != (after_manifest is None):
        raise ValueError(f"{spec.manifest} was added or removed")
    if before_manifest is not None and after_manifest is not None:
        old_manifest = _unpinned_manifest(_toml(before_manifest, spec.manifest), spec)
        new_manifest = _unpinned_manifest(_toml(after_manifest, spec.manifest), spec)
        if old_manifest != new_manifest:
            raise ValueError(f"{spec.manifest} changes more than the {spec.name} pin")
    return move


def refuse_pytest_plugin(
    spec: FirstPartyPackage, repo: Path, files: dict[str, str], extra_files: tuple[str, ...] = ()
) -> None:
    """
    Refuse to narrow a package that the consumer's pytest configuration names.

    `-p backend_common.x` loads a module into every test without any Python file importing it, so
    import analysis cannot see its changes. Any mention is refused, not only `-p`: a false refusal
    costs one complete suite, a missed plugin silently skips tests.
    """
    for path, policy in pytest_policies(repo, files, extra_files).items():
        if spec.import_prefix in policy:
            raise ValueError(
                f"the pytest configuration in {path} names {spec.import_prefix}, so its changes reach every test"
            )


def _git_environment(spec: FirstPartyPackage, token: str | None) -> dict[str, str]:
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if token and spec.repository.startswith("https://"):
        host = spec.repository.split("/", 3)[2]
        credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        # Scoped to this child process and this host. Never written to any git config.
        environment |= {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credential}",
        }
    return environment


def _remove_tree(path: Path) -> None:
    """Delete a clone; git marks object files read-only, which Windows refuses to delete."""

    def writable(function, target, _error):  # noqa: ANN001 - shutil's callback contract
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=writable)
    else:
        shutil.rmtree(path, onerror=writable)


def _available_commits(repo: Path, commits: set[str]) -> set[str]:
    """Prove all requested objects are commits with one Git process."""
    if not commits:
        return set()
    ordered = sorted(commits)
    probe = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch-check=%(objecttype)"],
        input="".join(f"{commit}^{{commit}}\n" for commit in ordered).encode(),
        capture_output=True,
        check=True,
    )
    return {commit for commit, kind in zip(ordered, probe.stdout.splitlines(), strict=True) if kind == b"commit"}


def fetch_commits(spec: FirstPartyPackage, move: PinMove, cache_dir: Path, token: str | None) -> Path:
    """Fetch both pinned commits into a cached bare repository, from the declared URL only."""
    repo = cache_dir / hashlib.sha256(spec.repository.encode()).hexdigest()[:16]
    environment = _git_environment(spec, token)
    try:
        # The clone rides inside the `.test-impact` actions cache, which is deliberately bounded.
        # Every fetch is shallow, so its size is the commits in `shallow`; past the bound, start over.
        shallow = repo / "shallow"
        if shallow.exists() and len(shallow.read_text().split()) + 2 > MAX_CACHED_COMMITS:
            _remove_tree(repo)
        if not (repo / "HEAD").exists():
            repo.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", "--bare", str(repo)], capture_output=True, check=True)
        wanted = {move.old, move.new}
        available = _available_commits(repo, wanted)
        missing = sorted(wanted - available)
        if missing:
            # This shallow cache is bounded and rebuilt above; automatic maintenance
            # needlessly starts another process after every tiny fetch on Windows.
            # The older alias also supports our documented Git 2.24 minimum.
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "fetch",
                    "-q",
                    "--no-auto-gc",
                    "--no-tags",
                    "--depth=1",
                    spec.repository,
                    *missing,
                ],
                capture_output=True,
                check=True,
                env=environment,
                timeout=120,
            )
            # Existing objects were already proved; only fetched objects need another probe.
            available |= _available_commits(repo, set(missing))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        detail = getattr(error, "stderr", b"") or b""
        message = detail.decode(errors="replace").strip().splitlines()[-1:] if detail else [type(error).__name__]
        raise ValueError(
            f"could not compare {spec.name} {move.old[:12]}..{move.new[:12]}: fetch failed ({message[0] if message else ''})"
        ) from error
    for commit in (move.old, move.new):
        if commit not in available:
            raise ValueError(f"could not compare {spec.name}: {commit[:12]} is not in {spec.repository}")
    return repo


def _module_name(path: str, spec: FirstPartyPackage) -> str:
    parts = list(PurePosixPath(path).relative_to(spec.source_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _owning_subsystem(path: str, spec: FirstPartyPackage) -> str:
    """
    Directory treated as reading a changed non-Python file: the package's first-level subpackage.

    Nothing imports a markdown fragment or a shell script, so there is no edge to follow. The
    subsystem that ships it is the conservative owner; a file directly in the package root owns all.
    """
    parts = PurePosixPath(path).relative_to(spec.source_root).parts
    depth = 2 if len(parts) > 2 else 1
    return "/".join([spec.source_root, *parts[:depth]])


def package_change(
    spec: FirstPartyPackage,
    move: PinMove,
    *,
    cache: GraphCache,
    cache_dir: Path,
    token: str | None,
) -> PackageChange:
    """
    Installed files that differ between the pins, and the modules they reach inside the package.

    An identical pair of commits, or commits whose installed source is byte-identical, returns no
    change without resolving any graph.
    """
    if move.old == move.new:
        return PackageChange(installed_files=[], modules=[])
    repo = fetch_commits(spec, move, cache_dir, token)
    trees = [inventory(repo, commit) for commit in (move.old, move.new)]
    installed = [{path: oid for path, oid in tree.files.items() if within(path, spec.source_root)} for tree in trees]
    before, after = installed
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    if not changed:
        return PackageChange(installed_files=[], modules=[])
    python = {path for tree in installed for path in tree if path.endswith(".py")}
    seeds = {path for path in changed if path.endswith(".py")}
    for path in changed - seeds:
        owned = {candidate for candidate in python if within(candidate, _owning_subsystem(path, spec))}
        # A data-only subpackage has no module to follow, and any module may read it through
        # `importlib.resources` by name; with no provable owner, the whole package owns it.
        seeds |= owned or python
    # Resolved inside the installed source only: the package's own tests and tools never reach a
    # consumer. Old and new edges are unioned, so deleted or renamed modules keep their importers.
    config = ImpactConfig(module_roots=[spec.source_root], test_roots=[spec.source_root], test_patterns=[])
    try:
        snapshots = [
            resolve_graph(
                tree.tree,
                files,
                cache.parse_python(repo, files),
                config,
                [link for link in tree.links if within(link, spec.source_root)],
            )
            for tree, files in zip(trees, installed, strict=True)
        ]
    except ValueError as error:
        raise ValueError(f"could not compare {spec.name}: {error}") from error
    reverse = reverse_edges(union_edges(*snapshots))
    affected = reachable(reverse, seeds) & python
    return PackageChange(
        installed_files=sorted(changed),
        modules=sorted({_module_name(path, spec) for path in affected}),
    )


def importers(candidates_by_file: dict[str, list[str]], prefix: str, modules: set[str]) -> set[str]:
    """
    Consumer files naming any changed module, or a module whose ancestor package changed.

    Importing ``a.b.c`` executes ``a`` and ``a.b`` first, so a change to either reaches it.
    """
    selected: set[str] = set()
    for path, candidates in candidates_by_file.items():
        for candidate in candidates:
            if candidate != prefix and not candidate.startswith(prefix + "."):
                continue
            parts = candidate.split(".")
            if any(".".join(parts[:end]) in modules for end in range(1, len(parts) + 1)):
                selected.add(path)
                break
    return selected
