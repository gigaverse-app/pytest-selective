"""File-level selection using both sides of a change, with broad fallbacks."""

import time
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from pytest_selective.impact_first_party import (
    first_party_pin_move,
    importers,
    package_change,
    refuse_pytest_plugin,
)
from pytest_selective.impact_graph import (
    DependencyDeclarationError,
    GraphCache,
    blobs,
    changed_paths,
    inventory,
    matches,
    reachable,
    reverse_edges,
    seed_nodes,
    union_edges,
)
from pytest_selective.impact_models import FirstPartyPackage, ImpactConfig, ImpactModel, ImpactReport, Snapshot
from pytest_selective.impact_name_scope import NotNarrowed, narrow_name_scoped_change


class NarrowedPin(ImpactModel):
    """A proven first-party pin move and what it reaches in the consumer."""

    reached: list[str]
    reason: str
    #: The pinned commits install byte-identical files.
    installed_unchanged: bool


def _blob(repo: Path, snapshot: Snapshot, path: str) -> bytes | None:
    oid = snapshot.files.get(path)
    return blobs(repo, {oid})[oid] if oid else None


def _content_readers(snapshots: tuple[Snapshot, Snapshot], inputs: set[str]) -> set[str]:
    """
    Files that read a narrowed lock or manifest themselves, rather than through a conftest.

    A conftest declares these to say the whole pytest run uses the installed dependency set; that is
    the claim the first-party proof replaces. Any other declaring file reads the file as content
    (a pin-consistency test, for one) and must still run whenever it changes.
    """
    markers = seed_nodes(sorted(inputs))
    return {
        path
        for snapshot in snapshots
        for path, deps in snapshot.edges.items()
        if PurePosixPath(path).name != "conftest.py" and markers & set(deps)
    }


def _narrow_first_party_pin(
    spec: FirstPartyPackage,
    repo: Path,
    snapshots: tuple[Snapshot, Snapshot],
    cache: GraphCache,
    dependency_cache: Path,
    dependency_token: str | None,
    pytest_config_files: tuple[str, ...] = (),
) -> NarrowedPin:
    """Prove the pin move, then return the consumer files it reaches and why."""
    before, after = snapshots
    before_lock, after_lock = _blob(repo, before, spec.lock), _blob(repo, after, spec.lock)
    if before_lock is None or after_lock is None:
        raise ValueError(f"{spec.lock} was added or removed")
    move = first_party_pin_move(
        spec,
        before_lock=before_lock,
        after_lock=after_lock,
        before_manifest=_blob(repo, before, spec.manifest),
        after_manifest=_blob(repo, after, spec.manifest),
    )
    refuse_pytest_plugin(spec, repo, after.files, pytest_config_files)
    change = package_change(spec, move, cache=cache, cache_dir=dependency_cache, token=dependency_token)
    candidates: dict[str, list[str]] = {}
    for snapshot in snapshots:
        for path, names in snapshot.unresolved.items():
            candidates.setdefault(path, []).extend(names)
    reached = importers(candidates, spec.import_prefix, set(change.modules))
    return NarrowedPin(
        reached=sorted(reached),
        reason=(
            f"first-party pin {spec.name} {move.old[:12]}..{move.new[:12]}: "
            f"{len(change.installed_files)} installed files changed; "
            f"{len(change.modules)} changed modules reach {len(reached)} files"
        ),
        installed_unchanged=not change.installed_files,
    )


def base_snapshot(repo: Path, base: str, config: ImpactConfig, cache: GraphCache, config_path: str | None) -> Snapshot:
    """
    The base graph under the base's own configuration, or an operational failure.

    The adoption commit must retain the old global edges, so the base is read with the config it
    carried at `config_path`: a new startup check cannot be required to exist in the tree preceding
    its introduction. With no config of its own there (moved, kept outside the repo, adopted in this
    change) the head's declarations are all there is, and they may name files the base does not
    have. Either way a failure here is about a tree this change cannot edit, so it is never a
    `DependencyDeclarationError` (exit 2, no fallback) but a missing proof: the complete suite.
    """
    # Other base failures (a changed pytest policy, an unsupported symlink) keep their own messages;
    # they were already operational.
    try:
        before_config = config
        if config_path and (oid := inventory(repo, base).files.get(config_path)):
            before_config = ImpactConfig.model_validate_json(blobs(repo, {oid})[oid])
        return cache.snapshot(repo, base, before_config)
    except (DependencyDeclarationError, ValidationError) as error:
        raise RuntimeError(f"base {base} cannot be described by its test-impact configuration: {error}") from error


def affected(
    repo: Path,
    base: str,
    head: str,
    config: ImpactConfig,
    cache: GraphCache,
    extra_files: list[str] | None = None,
    config_path: str | None = None,
    dependency_cache: Path | None = None,
    dependency_token: str | None = None,
) -> ImpactReport:
    start = time.perf_counter()
    # Head first: its declaration errors are the only ones this change can fix.
    after = cache.snapshot(repo, head, config)
    before = base_snapshot(repo, base, config, cache, config_path)
    changed = changed_paths(before, after)
    if extra_files:
        changed = sorted(set(changed) | set(extra_files))
    # Declarations/imports are stronger evidence than historical path exclusions.
    # Unreferenced files naturally reach no tests without extension-based rules.
    relevant = changed
    parse_errors = sorted(
        {
            f"{path}: {reason}"
            for snapshot in (before, after)
            for path, issues in snapshot.opaque.items()
            for reason in issues
            if reason.startswith("cannot parse:")
        }
    )
    # Invalid source cannot prove scope. Use the existing hard-error exit path,
    # never the operational fallback that allocates a complete test suite.
    if parse_errors:
        raise DependencyDeclarationError("Unparseable Python dependency: " + "; ".join(parse_errors))
    selected: set[str] = set()
    reasons: list[str] = []
    # A lock or manifest is a global input only because it can change any installed package. When
    # the sole change is a declared first-party pin, replace it with the files the moved modules
    # actually reach. Every failure to prove that leaves the global input in place.
    narrowed: set[str] = set()
    reached: set[str] = set()
    name_readers: set[str] = set()
    # Proven only by a declaration: with nothing declared the environment is unknown, not unchanged.
    dependencies_unchanged = bool(config.first_party_packages)
    for spec in config.first_party_packages:
        pinned = {spec.lock, spec.manifest} & set(changed)
        if not pinned:
            continue
        try:
            pin = _narrow_first_party_pin(
                spec,
                repo,
                (before, after),
                cache,
                dependency_cache or repo / ".test-impact" / "dependencies",
                dependency_token,
                tuple(config.pytest_config_files),
            )
        except ValueError as error:
            reasons.append(f"{spec.name} pin not narrowed: {error}; {spec.lock} and {spec.manifest} stay global inputs")
            dependencies_unchanged = False
            continue
        narrowed |= pinned
        reached |= set(pin.reached) | _content_readers((before, after), pinned)
        reasons.append(pin.reason)
        dependencies_unchanged = dependencies_unchanged and pin.installed_unchanged
    # A name-scoped module's importers depend only on the names they read. When a change only
    # rebinds names, replace the module with the files that read them; anything unproven keeps its edges.
    for module in config.name_scoped_modules:
        if module.file not in changed:
            continue
        try:
            scoped = narrow_name_scoped_change(repo, (before, after), config, module)
        except NotNarrowed as error:
            reasons.append(f"{module.file} not narrowed: {error}; every file that loads it stays selected")
        else:
            narrowed.add(module.file)
            name_readers |= scoped.readers
            reasons.append(scoped.reason)
    if narrowed:
        relevant = sorted((set(relevant) - narrowed) | reached | name_readers)
    if relevant:
        reverse = reverse_edges(union_edges(before, after))
        # A name-scoped reader's own file did not change, only a name it reads, so files that read its
        # contents are unaffected: it seeds its importers, not its content readers. Without this, a
        # narrowed change could select tests the module's ordinary dependents never reach.
        unchanged_readers = name_readers - set(changed)
        impacted = reachable(reverse, seed_nodes(sorted(set(relevant) - unchanged_readers)) | unchanged_readers)
        # Only changed inputs seed selection. Helpers use ordinary import edges;
        # the graph already includes pytest's implicit ancestor-conftest edges.
        # Non-import inputs must be declared rather than making every unknown
        # reader a root on every push.
        selected.update(impacted & set(after.tests))
        selected.update(test for test in after.tests if matches(test, config.always_run))
        reasons.append(f"dependency closure: {len(impacted & set(after.tests))} test files")
    return ImpactReport(
        mode="full" if selected and len(selected) == len(after.tests) else "scoped" if selected else "none",
        dependencies_unchanged=dependencies_unchanged,
        base=before.tree,
        head=after.tree,
        changed=changed,
        seeds=sorted(relevant),
        selected=sorted(selected),
        total_files=len(after.tests),
        reasons=reasons,
        elapsed_seconds=time.perf_counter() - start,
        parsed_blobs=cache.parsed_blobs,
        snapshot_hits=cache.snapshot_hits,
    )
