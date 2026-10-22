"""
First-party dependency pins select the tests that import what moved, not every test.

Consumers declare the lock file and manifest as inputs of their root conftest, because the whole
pytest invocation runs on that installed dependency set. That makes every lock change a complete
suite. For a first-party package the change is knowable: both pinned commits are in a repository we
own, so the modules that actually differ, and everything inside the package that imports them, can
be computed. Each case below builds a real dependency repository, a real consumer repository that
pins it through a uv-style lock and manifest, and runs the production selector over the pin move.
"""

import subprocess
from pathlib import Path

import pytest

from pytest_selective import impact_first_party
from pytest_selective.impact_cli import main
from pytest_selective.impact_first_party import PinMove, first_party_pin_move
from pytest_selective.impact_graph import GraphCache, inventory, policy_fingerprints
from pytest_selective.impact_models import FirstPartyPackage, ImpactConfig
from pytest_selective.impact_selection import affected
from tests.testing.git_repo import commit, init, write

PACKAGE = "acme-shared"
MODULE = "acme_shared"


@pytest.fixture
def dependency(tmp_path: Path) -> Path:
    """
    A first-party package whose `cli` reaches `sharding` only through an import.

    That indirection is the point: a consumer importing `cli` is affected by a change to
    `sharding` even though it never names it.
    """
    root = tmp_path / "shared"
    init(root)
    # A real host (GitHub) serves any reachable commit by SHA; a local upload-pack needs this.
    subprocess.run(["git", "-C", str(root), "config", "uploadpack.allowAnySHA1InWant", "true"], check=True)
    write(root, f"src/{MODULE}/__init__.py")
    write(root, f"src/{MODULE}/testing/__init__.py")
    write(root, f"src/{MODULE}/testing/sharding.py", "SHARDS = 1\n")
    write(root, f"src/{MODULE}/testing/cli.py", f"from {MODULE}.testing.sharding import SHARDS\n")
    write(root, f"src/{MODULE}/kafka.py", "BROKERS = 1\n")
    write(root, "tests/test_sharding.py", "def test_shards(): pass\n")
    write(root, ".github/workflows/ci.yaml", "name: ci\n")
    return root


PACKAGE_VERSION = "1.0.0"
PACKAGE_DEPENDENCIES = '[{ name = "httpx" }]'


def lock(
    url: str,
    ref: str,
    sha: str,
    extra: str = "",
    *,
    package_version: str = PACKAGE_VERSION,
    package_dependencies: str = PACKAGE_DEPENDENCIES,
) -> str:
    return (
        "version = 1\n"
        "revision = 3\n"
        'requires-python = ">=3.12"\n\n'
        "[manifest]\n"
        f'requirements = [{{ name = "{PACKAGE}", git = "{url}?rev={ref}" }}]\n\n'
        "[[package]]\n"
        f'name = "{PACKAGE}"\n'
        f'version = "{package_version}"\n'
        f'source = {{ git = "{url}?rev={ref}#{sha}" }}\n'
        f"dependencies = {package_dependencies}\n\n"
        "[[package]]\n"
        'name = "httpx"\n'
        f'version = "{extra or "0.28.1"}"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    )


def manifest(url: str, ref: str, extra_dependency: str = "", *, pytest_addopts: str = "") -> str:
    dependencies = [f'"{PACKAGE}"', '"httpx"', *([f'"{extra_dependency}"'] if extra_dependency else [])]
    pytest_section = f'\n[tool.pytest.ini_options]\naddopts = "{pytest_addopts}"\n' if pytest_addopts else ""
    return (
        "[project]\n"
        'name = "consumer"\n'
        'version = "0"\n'
        f"dependencies = [{', '.join(dependencies)}]\n\n"
        "[tool.uv.sources]\n"
        f'{PACKAGE} = {{ git = "{url}", rev = "{ref}" }}\n'
        f"{pytest_section}"
    )


@pytest.fixture
def consumer(tmp_path: Path) -> Path:
    """
    A consumer whose root conftest makes the lock and manifest global inputs.

    `test_cli` imports the package entry point, `test_kafka` an unrelated module, `test_local`
    nothing from the package at all, and `test_lock` reads the lock file itself.
    """
    root = tmp_path / "consumer"
    init(root)
    write(
        root,
        "conftest.py",
        "# gv:test-dependency: pyproject.toml\n# gv:test-dependency: uv.lock\n",
    )
    write(root, "tests/test_cli.py", f"from {MODULE}.testing import cli\ndef test_cli(): pass\n")
    write(root, "tests/test_kafka.py", f"import {MODULE}.kafka\ndef test_kafka(): pass\n")
    write(root, "tests/test_local.py", "def test_local(): pass\n")
    write(root, "tests/test_lock.py", "# gv:test-dependency: uv.lock\ndef test_lock(): pass\n")
    return root


@pytest.fixture
def config(dependency: Path) -> ImpactConfig:
    return ImpactConfig(
        module_roots=["."],
        test_roots=["tests"],
        first_party_packages=[FirstPartyPackage(name=PACKAGE, repository=dependency.as_uri(), import_prefix=MODULE)],
    )


@pytest.fixture
def cache(tmp_path: Path):
    cache = GraphCache(tmp_path / "cache.sqlite3")
    yield cache
    cache.close()


def pin(
    consumer: Path,
    url: str,
    ref: str,
    sha: str,
    *,
    lock_extra: str = "",
    manifest_extra: str = "",
    package_version: str = PACKAGE_VERSION,
    package_dependencies: str = PACKAGE_DEPENDENCIES,
    pytest_addopts: str = "",
) -> str:
    write(
        consumer,
        "uv.lock",
        lock(url, ref, sha, lock_extra, package_version=package_version, package_dependencies=package_dependencies),
    )
    write(consumer, "pyproject.toml", manifest(url, ref, manifest_extra, pytest_addopts=pytest_addopts))
    return commit(consumer)


def select(consumer: Path, base: str, head: str, config: ImpactConfig, cache: GraphCache, tmp_path: Path):
    # The fingerprint covers only `[tool.pytest]`, which no pin move here touches, so the head's
    # reviewed policy is also the base's.
    reviewed = config.model_copy(
        update={
            "pytest_policy": policy_fingerprints(consumer, inventory(consumer, head), tuple(config.pytest_config_files))
        }
    )
    return affected(consumer, base, head, reviewed, cache, dependency_cache=tmp_path / "deps")


def test_a_changed_module_selects_only_the_tests_that_reach_it(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: a pin move runs the tests that import the changed module, directly or not.

    Falsifies the lock-as-global-input behaviour, which selects all four files, and a
    direct-import-only analysis, which misses `test_cli` because it imports `cli`, not `sharding`.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, config, cache, tmp_path)

    # `test_lock` reads the lock file's contents, so a lock edit is its own input.
    assert report.selected == ["tests/test_cli.py", "tests/test_lock.py"]
    assert report.mode == "scoped"
    assert report.dependencies_unchanged is False
    assert any(f"{PACKAGE} {old[:12]}..{new[:12]}" in reason for reason in report.reasons)


def test_a_repin_to_an_identical_tree_selects_no_package_importers(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: moving a pin between commits with the same package contents runs no importers.

    This is the post-merge `PR<N>` to `v<N>` repin: a new commit, the same tree. Before this, it
    re-ran every consumer test on code that had just passed.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    new = commit(dependency, "merge commit with no file changes")
    head = pin(consumer, dependency.as_uri(), "v1", new)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.selected == ["tests/test_lock.py"]
    # Nothing installed differs, so lanes that treat a lock change as global may skip.
    assert report.dependencies_unchanged is True


def test_changes_outside_the_installed_source_select_no_package_importers(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: only files the package installs can change a consumer's runtime.

    The package's own tests and workflows ride along in the same commit but never reach the
    consumer's interpreter.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, "tests/test_sharding.py", "def test_shards(): assert True\n")
    write(dependency, ".github/workflows/ci.yaml", "name: ci changed\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.selected == ["tests/test_lock.py"]
    assert report.dependencies_unchanged is True


def test_a_changed_package_initializer_reaches_every_importer_beneath_it(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """INVARIANT: importing any submodule executes its ancestors' initializers."""
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/__init__.py", "LOADED = True\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.selected == ["tests/test_cli.py", "tests/test_kafka.py", "tests/test_lock.py"]


def test_a_changed_data_file_reaches_the_subsystem_that_ships_it(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: a packaged non-Python file is treated as changing the subsystem that contains it.

    Nothing imports a markdown fragment or shell script, so there is no edge to follow; the
    subsystem directory is the conservative owner.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/scripts/collect.sh", "echo collect\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.selected == ["tests/test_cli.py", "tests/test_lock.py"]
    # A data file installs, so the environment differs even though no module changed.
    assert report.dependencies_unchanged is False


def test_another_locked_package_changing_keeps_the_complete_suite(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    CONTROL: only a lock whose sole difference is the first-party pin is narrowed.

    A third-party upgrade can change any test's behaviour, which is exactly what the root
    conftest's global declaration exists to catch.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new, lock_extra="0.29.0")

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.mode == "full"
    assert report.dependencies_unchanged is False
    assert any("httpx" in reason for reason in report.reasons)


def test_a_manifest_change_beyond_the_pin_keeps_the_complete_suite(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """CONTROL: a new direct dependency is not a pin move, even when the lock pin also moved."""
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new, manifest_extra="rich")

    assert select(consumer, base, head, config, cache, tmp_path).mode == "full"


def test_an_unreachable_package_repository_keeps_the_complete_suite(
    dependency: Path, consumer: Path, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: selection is narrowed only on proof; a fetch that fails proves nothing.

    Missing credentials, a network error or a force-pushed commit all read as "cannot compare",
    which falls back to the global declaration rather than to an empty selection.
    """
    missing = (tmp_path / "missing").as_uri()
    unreachable = ImpactConfig(
        module_roots=["."],
        test_roots=["tests"],
        first_party_packages=[FirstPartyPackage(name=PACKAGE, repository=missing, import_prefix=MODULE)],
    )
    old = commit(dependency)
    base = pin(consumer, missing, "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, missing, "PR1", new)

    report = select(consumer, base, head, unreachable, cache, tmp_path)

    assert report.mode == "full"
    assert report.dependencies_unchanged is False
    assert any("could not compare" in reason for reason in report.reasons)


def test_a_lock_that_names_another_repository_is_never_fetched_or_narrowed(
    dependency: Path, consumer: Path, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: the package is fetched only from the repository the configuration declares.

    The lock is part of the change under test. Taking the fetch URL from it would let a pull request
    aim the dependency token at any host it likes; a lock that disagrees with the declaration is
    simply not a recognized pin move.
    """
    elsewhere = ImpactConfig(
        module_roots=["."],
        test_roots=["tests"],
        first_party_packages=[
            FirstPartyPackage(name=PACKAGE, repository="https://example.invalid/acme/shared.git", import_prefix=MODULE)
        ],
    )
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, elsewhere, cache, tmp_path)

    assert report.mode == "full"
    assert any("does not match the declared repository" in reason for reason in report.reasons)
    assert not (tmp_path / "deps").exists(), "a mismatched source must not trigger any fetch"


def test_a_consumer_that_declares_no_first_party_package_is_unchanged(
    dependency: Path, consumer: Path, cache: GraphCache, tmp_path: Path
) -> None:
    """CONTROL: the narrowing is opt-in; without a declaration a lock change stays global."""
    plain = ImpactConfig(module_roots=["."], test_roots=["tests"])
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, plain, cache, tmp_path)

    assert report.mode == "full"
    # Without a declaration the environment is unknown, never "unchanged".
    assert report.dependencies_unchanged is False


def test_other_changes_in_the_same_diff_still_select_normally(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """CONTROL: narrowing the pin move leaves every other changed input's closure intact."""
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    new = commit(dependency)
    write(consumer, "tests/test_local.py", "def test_local(): assert True\n")
    head = pin(consumer, dependency.as_uri(), "v1", new)

    assert select(consumer, base, head, config, cache, tmp_path).selected == [
        "tests/test_local.py",
        "tests/test_lock.py",
    ]


def test_the_published_selection_uses_the_narrowed_pin(
    dependency: Path, consumer: Path, config: ImpactConfig, tmp_path: Path
) -> None:
    """
    INVARIANT: the CLI the action runs publishes the narrowed files, not every test root.

    Falsifies wiring that narrows the library result but never passes the dependency cache, which
    would leave every CI run on the global behaviour.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    new = commit(dependency, "repin without file changes")
    head = pin(consumer, dependency.as_uri(), "v1", new)
    reviewed = config.model_copy(
        update={
            "pytest_policy": policy_fingerprints(consumer, inventory(consumer, head), tuple(config.pytest_config_files))
        }
    )
    config_path = tmp_path / "impact.json"
    config_path.write_text(reviewed.model_dump_json())
    output = tmp_path / "github-output"

    assert (
        main(
            [
                "affected",
                "--repo",
                str(consumer),
                "--config",
                str(config_path),
                "--cache",
                str(tmp_path / "cli-cache.sqlite3"),
                "--base",
                base,
                "--head",
                head,
                "--dependency-cache",
                str(tmp_path / "cli-deps"),
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    published = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    assert published["mode"] == "scoped"
    assert published["test_roots"] == "tests/test_lock.py"
    assert published["dependencies_unchanged"] == "true"


def test_an_untouched_lock_reports_an_unchanged_environment(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """CONTROL: a diff that never touches the lock or manifest leaves the environment unchanged."""
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(consumer, "tests/test_local.py", "def test_local(): assert True\n")
    head = commit(consumer)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.selected == ["tests/test_local.py"]
    assert report.dependencies_unchanged is True


def test_a_changed_module_named_only_in_a_dotted_attribute_string_is_reached(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: a consumer naming `pkg.module.attribute` depends on `pkg.module`.

    Patch targets are the common case: `patch("backend_common.x.func")` imports nothing, and the
    last segment is an attribute, not a module, so only an ancestor of the string can match.
    """
    write(consumer, "tests/test_patched.py", f'TARGET = "{MODULE}.testing.sharding.SHARDS"\ndef test_patched(): pass\n')
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    assert select(consumer, base, head, config, cache, tmp_path).selected == [
        "tests/test_cli.py",
        "tests/test_lock.py",
        "tests/test_patched.py",
    ]


def test_the_packages_own_version_moving_with_its_pin_is_still_a_pin_move(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: the package's own lock entry follows its source and is not an environment change.

    A backend-common release bumps its version in the same commit as the code. Reading that as a
    third-party change would send every such pin move back to the complete suite.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new, package_version="1.1.0")

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.mode == "scoped"
    assert report.selected == ["tests/test_cli.py", "tests/test_lock.py"]


def test_a_data_file_in_a_subpackage_without_python_reaches_every_importer(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: an installed file nothing can be proven to own is owned by the whole package.

    A data-only subpackage has no Python file to follow, and any module may read it through
    `importlib.resources` by name. Seeding nothing there would silently skip its readers.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/assets/catalog.json", "{}\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.selected == ["tests/test_cli.py", "tests/test_kafka.py", "tests/test_lock.py"]
    assert report.dependencies_unchanged is False


@pytest.mark.parametrize("custom_config", [False, True])
def test_a_package_loaded_as_a_pytest_plugin_keeps_the_complete_suite(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path, custom_config: bool
) -> None:
    """
    INVARIANT: a package pytest loads by configuration is global, whatever imports it.

    `-p acme_shared.testing.plugin` runs inside every test and no Python file names it, so import
    analysis would never reach its changes.
    """
    plugin = f"-p {MODULE}.testing.plugin"
    if custom_config:
        config.pytest_config_files = ["ci/custom.conf"]
        write(consumer, "ci/custom.conf", f"[pytest]\naddopts = {plugin}\n")
        plugin = ""
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old, pytest_addopts=plugin)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new, pytest_addopts=plugin)

    report = select(consumer, base, head, config, cache, tmp_path)

    assert report.mode == "full"
    assert any("pytest configuration" in reason for reason in report.reasons)


def test_dependency_parsing_shares_the_graph_cache(
    dependency: Path, consumer: Path, config: ImpactConfig, cache: GraphCache, tmp_path: Path
) -> None:
    """
    INVARIANT: the package's sources parse through the same cache, and count, as the consumer's.

    A second parsing path with its own cache keys and bookkeeping is how the parse count drifted.
    """
    old = commit(dependency)
    base = pin(consumer, dependency.as_uri(), "PR1", old)
    write(dependency, f"src/{MODULE}/testing/sharding.py", "SHARDS = 2\n")
    new = commit(dependency)
    head = pin(consumer, dependency.as_uri(), "PR1", new)
    plain = GraphCache(tmp_path / "plain.sqlite3")
    try:
        consumer_only = select(
            consumer, base, head, config.model_copy(update={"first_party_packages": []}), plain, tmp_path
        )
    finally:
        plain.close()

    first = select(consumer, base, head, config, cache, tmp_path)
    second = select(consumer, base, head, config, cache, tmp_path)

    assert first.parsed_blobs > consumer_only.parsed_blobs, "dependency blobs must count as parsed"
    assert second.parsed_blobs == first.parsed_blobs, "a warm cache must not parse the package again"


def test_the_clone_cache_stays_bounded(dependency: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    INVARIANT: the cached clone never holds more than the bound, however many pins it has served.

    It travels inside the `.test-impact` actions cache, which is deliberately bounded.
    """
    monkeypatch.setattr(impact_first_party, "MAX_CACHED_COMMITS", 3)
    spec = FirstPartyPackage(name=PACKAGE, repository=dependency.as_uri(), import_prefix=MODULE)
    commits = []
    for index in range(6):
        write(dependency, f"src/{MODULE}/kafka.py", f"BROKERS = {index}\n")
        commits.append(commit(dependency))
    for old, new in zip(commits, commits[1:]):
        clone = impact_first_party.fetch_commits(spec, PinMove(old=old, new=new), tmp_path / "deps", None)
        assert len((clone / "shallow").read_text().split()) <= 3


# --- the pin-move proof on its own, without repositories ------------------------------------------

URL = "https://github.com/acme/shared.git"
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
SPEC = FirstPartyPackage(name=PACKAGE, repository=URL, import_prefix=MODULE)


def test_the_proof_names_both_pinned_commits() -> None:
    move = first_party_pin_move(
        SPEC,
        before_lock=lock(URL, "PR7", OLD_SHA).encode(),
        after_lock=lock(URL, "v7", NEW_SHA).encode(),
        before_manifest=manifest(URL, "PR7").encode(),
        after_manifest=manifest(URL, "v7").encode(),
    )

    assert move == PinMove(old=OLD_SHA, new=NEW_SHA)


def test_a_lock_without_a_commit_in_the_pinned_source_proves_nothing() -> None:
    """A path or registry source has no commit to compare, so the move cannot be characterized."""
    unpinned = lock(URL, "PR7", OLD_SHA).replace(f"#{OLD_SHA}", "")

    with pytest.raises(ValueError, match="commit"):
        first_party_pin_move(
            SPEC,
            before_lock=unpinned.encode(),
            after_lock=lock(URL, "PR7", NEW_SHA).encode(),
            before_manifest=manifest(URL, "PR7").encode(),
            after_manifest=manifest(URL, "PR7").encode(),
        )


def test_batch_probe_preserves_commit_type_and_missing_object_checks(dependency: Path):
    old = commit(dependency)
    write(dependency, "another.py", "VALUE = 1\n")
    new = commit(dependency)
    tree = subprocess.check_output(["git", "-C", str(dependency), "rev-parse", "HEAD^{tree}"], text=True).strip()
    missing = "0" * 40
    assert impact_first_party._available_commits(dependency, {old, new, tree, missing}) == {old, new}
    assert impact_first_party._available_commits(dependency, {old}) == {old}
    assert impact_first_party._available_commits(dependency, set()) == set()
