"""Exercise the editing guard through real Git histories and its public CLI."""

import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest
import yaml

from pytest_selective import pytest_expansion
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.impact_selection import affected

SCRIPT = Path(__file__).resolve().parents[1] / "src/pytest_selective/pytest_expansion.py"
ACTIVATION = "# gv:test-requires-expansion-reason\n"
BASE = ACTIVATION + "import pytest\n\n@pytest.fixture\ndef existing():\n    return 1\n"
REASON = "# pytest-global: Isolates shared state used by both application and perf tests.\n"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)


def commit(root: Path) -> str:
    git(root, "add", ".")
    git(root, "-c", "maintenance.auto=false", "commit", "--quiet", "-m", "test snapshot")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.name", "Policy test")
    git(tmp_path, "config", "user.email", "policy@example.invalid")
    write(tmp_path, "conftest.py", BASE)
    commit(tmp_path)
    return tmp_path


def check(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(root),
            "--project-import-prefix",
            "gigaverse",
            "--follow-import-prefix",
            "gigaverse.core.shared.tests.harness",
            *args,
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "addition",
    [
        "@pytest.fixture\ndef customer(): return 2\n",
        "class CustomerScenario: pass\n",
        "pytest_plugins = ['gigaverse.domain.plugin']\n",
        "from gigaverse.core.streams.services import RoomsService\n",
        "def helper():\n    from gigaverse.core.streams.services import RoomsService\n",
        "from pytest import fixture as fx\n@fx\ndef customer(): return 2\n",
        "import pytest as pt\n@pt.fixture\ndef customer(): return 2\n",
    ],
)
def test_unexplained_expansion_is_rejected(repo: Path, addition: str) -> None:
    write(repo, "conftest.py", BASE + "\n" + addition)
    result = check(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "conftest.py:" in result.stdout
    assert "pytest-global:" in result.stdout
    assert "narrowest" in result.stdout


@pytest.mark.parametrize(
    "addition",
    [
        "@pytest.fixture\ndef customer(): return 2\n",
        "class CustomerScenario: pass\n",
        "pytest_plugins = ['gigaverse.domain.plugin']\n",
        "from gigaverse.core.streams.services import RoomsService\n",
    ],
)
def test_local_explanation_is_the_escape_hatch(repo: Path, addition: str) -> None:
    write(repo, "conftest.py", BASE + "\n" + REASON + addition)
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Isolates shared state" in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        BASE.replace("return 1", "return 2"),
        BASE.replace("existing", "renamed"),
        BASE.replace("import pytest", "import pytest as pt").replace("@pytest.fixture", "@pt.fixture"),
        BASE + "\ndef helper(): return 2\n",
        "import pytest\n",
        BASE.replace("@pytest.fixture", "@pytest.fixture(scope='function', autouse=False)"),
    ],
)
def test_ordinary_maintenance_needs_no_policy_update(repo: Path, source: str) -> None:
    write(repo, "conftest.py", source)
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("decorator", ["@pytest.fixture(scope='session')", "@pytest.fixture(autouse=True)"])
def test_broadening_requires_a_fresh_reason(repo: Path, decorator: str) -> None:
    write(repo, "conftest.py", BASE.replace("@pytest.fixture", REASON + "@pytest.fixture"))
    commit(repo)
    widened = BASE.replace("@pytest.fixture", REASON + decorator)
    write(repo, "conftest.py", widened)
    assert check(repo).returncode == 1
    write(repo, "conftest.py", widened.replace("Isolates shared state", "Now isolates session-wide shared state"))
    assert check(repo).returncode == 0


def test_narrowing_is_allowed(repo: Path) -> None:
    write(repo, "conftest.py", BASE.replace("@pytest.fixture", "@pytest.fixture(scope='session', autouse=True)"))
    commit(repo)
    write(repo, "conftest.py", BASE)
    assert check(repo).returncode == 0


def test_alias_rearrangement_does_not_add_an_import(repo: Path) -> None:
    write(repo, "conftest.py", BASE + "\nfrom gigaverse.core.streams.services import RoomsService\n")
    commit(repo)
    write(repo, "conftest.py", BASE + "\nfrom gigaverse.core.streams.services import RoomsService as Rooms\n")
    assert check(repo).returncode == 0


def test_imported_global_helper_is_checked_without_conftest_edits(repo: Path) -> None:
    helper = "gigaverse/core/shared/tests/harness/cleanup.py"
    write(repo, helper, "def cleanup(): pass\n")
    write(repo, "conftest.py", BASE + "\nfrom gigaverse.core.shared.tests.harness import cleanup\n")
    commit(repo)
    write(repo, helper, "from gigaverse.core.streams.services import RoomsService\n")
    result = check(repo)
    assert result.returncode == 1
    assert helper in result.stdout


def test_registered_plugin_is_checked(repo: Path) -> None:
    helper = "gigaverse/core/shared/tests/harness/plugin.py"
    write(repo, helper, "import pytest\n")
    write(repo, "conftest.py", BASE + "\npytest_plugins = ['gigaverse.core.shared.tests.harness.plugin']\n")
    commit(repo)
    write(repo, helper, "import pytest\n@pytest.fixture(autouse=True)\ndef unsafe(): pass\n")
    assert check(repo).returncode == 1


def test_registered_plugin_is_followed_when_native_paths_are_windows_paths(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Git names paths with forward slashes on every OS; module resolution must not use native ones.

    On Windows `Path` is a WindowsPath, so joining a module root to a module suffix produced
    `gigaverse\\core\\...\\plugin.py`, which never matched Git's `gigaverse/core/.../plugin.py`. No
    import was followed and the pre-commit guard passed while Linux CI blocked the same diff.
    Substituting the Windows flavour reproduces that on any OS.
    """
    helper = "gigaverse/core/shared/tests/harness/durable_effect_collection.py"
    write(repo, helper, "import pytest\n")
    write(
        repo,
        "conftest.py",
        BASE + "\npytest_plugins = ['gigaverse.core.shared.tests.harness.durable_effect_collection']\n",
    )
    commit(repo)
    write(repo, helper, "import pytest\n\nclass DurableEffectCollector: pass\n")
    monkeypatch.setattr(pytest_expansion, "Path", PureWindowsPath)

    failed = pytest_expansion.check(
        repo,
        "HEAD",
        None,
        module_roots=(".",),
        project_prefixes=("gigaverse",),
        follow_prefixes=("gigaverse.core.shared.tests.harness",),
    )

    output = capsys.readouterr().out
    assert failed == 1, output
    assert f"BLOCKED {helper}:3: class DurableEffectCollector" in output


# --- Moves and deletions: relocating existing infrastructure is not expansion ------------------
#
# The guard compares each module with the same path at the base. Without rename detection a moved
# file had no baseline, so every declaration in it, and every import naming the moved module, read
# as new: gigaverse-backend #5079 reorganised its harness and was blocked on ~196 declarations that
# all already existed on main.

HARNESS = "gigaverse.core.shared.tests.harness"
EFFECTS = "gigaverse/core/shared/tests/harness/effects.py"
MOVED_EFFECTS = "gigaverse/core/shared/tests/harness/due_work/effects.py"
# Unexplained on purpose: moving it must not demand a reason it never needed at the base.
EFFECTS_SOURCE = (
    "import pytest\n"
    "from gigaverse.core.streams.services import RoomsService\n\n"
    "@pytest.fixture(autouse=True)\n"
    "def collector():\n"
    "    return RoomsService()\n\n"
    "class EffectCollector:\n"
    "    def collect(self):\n"
    "        return []\n\n"
    "def pytest_runtest_setup(item):\n"
    "    pass\n"
)
NEW_IMPORT = "from gigaverse.core.streams.api import app\n"


def module(path: str) -> str:
    return path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def plugins(*paths: str) -> str:
    return BASE + f"\npytest_plugins = {[module(path) for path in paths]!r}\n"


def move(root: Path, old: str, new: str) -> None:
    """A plain filesystem move, unstaged: the local check must still see it as a rename."""
    (root / new).parent.mkdir(parents=True, exist_ok=True)
    (root / old).rename(root / new)


def blocked(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stdout.splitlines() if line.startswith("BLOCKED")]


@pytest.fixture
def effects_plugin(repo: Path) -> Path:
    write(repo, EFFECTS, EFFECTS_SOURCE)
    write(repo, "conftest.py", plugins(EFFECTS))
    commit(repo)
    return repo


def test_moving_a_loaded_plugin_is_not_expansion(effects_plugin: Path) -> None:
    move(effects_plugin, EFFECTS, MOVED_EFFECTS)
    write(effects_plugin, "conftest.py", plugins(MOVED_EFFECTS))
    unstaged = git(effects_plugin, "status", "--porcelain")
    result = check(effects_plugin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert blocked(result) == []
    assert git(effects_plugin, "status", "--porcelain") == unstaged  # Detection must not stage the move.


def test_a_new_import_inside_a_moved_file_is_still_expansion(effects_plugin: Path) -> None:
    base = git(effects_plugin, "rev-parse", "HEAD")
    move(effects_plugin, EFFECTS, MOVED_EFFECTS)
    write(effects_plugin, MOVED_EFFECTS, NEW_IMPORT + EFFECTS_SOURCE)
    write(effects_plugin, "conftest.py", plugins(MOVED_EFFECTS))
    commit(effects_plugin)
    result = check(effects_plugin, "--base", base, "--head", "HEAD")
    assert result.returncode == 1, result.stdout + result.stderr
    [only] = blocked(result)
    assert only.startswith(f"BLOCKED {MOVED_EFFECTS}:1: project-import gigaverse.core.streams.api.app:"), only


def test_copying_a_loaded_plugin_is_still_expansion(effects_plugin: Path) -> None:
    write(effects_plugin, MOVED_EFFECTS, EFFECTS_SOURCE)
    write(effects_plugin, "conftest.py", plugins(EFFECTS, MOVED_EFFECTS))
    result = check(effects_plugin)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"BLOCKED {MOVED_EFFECTS}:" in result.stdout
    assert f"BLOCKED {EFFECTS}:" not in result.stdout


def test_renaming_a_package_its_consumers_import_from_is_not_expansion(repo: Path) -> None:
    """`from pkg import Name` names the package's `__init__`, so the package itself must map too."""
    consumer = "gigaverse/core/shared/tests/harness/work.py"

    def snapshot(package: str) -> None:
        dotted = module(package)
        write(repo, f"{package}/__init__.py", "class Ledger:\n    entries: list[str] = []\n")
        write(repo, f"{package}/store.py", "class Store:\n    def load(self):\n        return {}\n")
        write(repo, consumer, f"from {dotted} import Ledger\nfrom {dotted}.store import Store\n")

    write(repo, "conftest.py", plugins(consumer))
    snapshot("gigaverse/core/shared/durable_effects")
    base = commit(repo)
    for stale in ("__init__.py", "store.py"):
        (repo / "gigaverse/core/shared/durable_effects" / stale).unlink()
    snapshot("gigaverse/core/shared/durable_work")
    commit(repo)
    result = check(repo, "--base", base, "--head", "HEAD")
    assert result.returncode == 0, result.stdout + result.stderr


def test_moving_a_protected_conftest_is_not_expansion(repo: Path) -> None:
    move(repo, "conftest.py", "tests/conftest.py")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_moving_a_conftest_up_the_tree_is_expansion(repo: Path) -> None:
    """A conftest's directory is its scope: moving it up reaches tests it never loaded for."""
    nested = "tests/sub/conftest.py"
    write(repo, nested, BASE.replace("@pytest.fixture", "@pytest.fixture(autouse=True, scope='session')"))
    commit(repo)
    move(repo, nested, "tests/conftest.py")
    result = check(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BLOCKED tests/conftest.py:" in result.stdout


def test_empty_package_initializers_are_not_paired_as_a_move(repo: Path) -> None:
    """
    Git pairs identical blobs arbitrarily; every empty `__init__.py` is the same blob.

    The package still moves by its name: its modules' moves agree on one destination.
    """
    consumer = "gigaverse/core/shared/tests/harness/work.py"
    write(repo, "gigaverse/harness_old/__init__.py", "")
    write(repo, "gigaverse/harness_old/tools.py", "class Tool:\n    def use(self):\n        return 1\n")
    write(repo, consumer, "import gigaverse.harness_old\n")
    write(repo, "conftest.py", plugins(consumer))
    commit(repo)
    for name in ("__init__.py", "tools.py"):
        move(repo, f"gigaverse/harness_old/{name}", f"gigaverse/zz_harness/{name}")
    write(repo, "gigaverse/app_new/__init__.py", "")
    write(repo, consumer, "import gigaverse.zz_harness\nimport gigaverse.app_new\n")
    result = check(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert [line.split(": ")[1] for line in blocked(result)] == ["project-import gigaverse.app_new"], result.stdout


@pytest.mark.parametrize("deleted", [EFFECTS, "conftest.py"])
def test_deleting_loaded_infrastructure_is_not_an_error(effects_plugin: Path, deleted: str) -> None:
    # The conftest keeps registering the deleted plugin: the guard reports policy, not import errors.
    (effects_plugin / deleted).unlink()
    result = check(effects_plugin)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_committed_head_and_pr_base_are_checked(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "conftest.py", BASE + "\n@pytest.fixture\ndef customer(): pass\n")
    commit(repo)
    # Local default checks uncommitted changes. CI must check the whole PR,
    # even when the offending commit is followed by an unrelated commit.
    write(repo, "README.md", "unrelated\n")
    commit(repo)
    write(repo, "conftest.py", BASE)  # Uncommitted fix must not excuse CI's head.
    assert check(repo, "--base", base, "--head", "HEAD").returncode == 1


def test_removing_activation_cannot_excuse_expansion_in_the_same_diff(repo: Path) -> None:
    write(repo, "conftest.py", BASE.replace(ACTIVATION, "") + "\n@pytest.fixture\ndef customer(): pass\n")
    result = check(repo)
    assert result.returncode == 1
    assert "fixture customer" in result.stdout


def test_missing_base_has_an_actionable_error(repo: Path) -> None:
    result = check(repo, "--base", "missing-ref")
    assert result.returncode == 1
    assert "fetch" in result.stdout.lower()


def test_unrelated_local_conftest_is_not_global(repo: Path) -> None:
    write(repo, "gigaverse/core/streams/tests/conftest.py", BASE.replace(ACTIVATION, "") + "\nclass Scenario: pass\n")
    assert check(repo).returncode == 0


def test_comment_can_activate_another_conftest(repo: Path) -> None:
    path = "gigaverse/core/streams/tests/conftest.py"
    write(repo, path, BASE.replace(ACTIVATION, ""))
    commit(repo)
    write(repo, path, BASE + "\nclass Scenario: pass\n")
    result = check(repo)
    assert result.returncode == 1
    assert path in result.stdout


def test_new_application_symbol_from_an_existing_module_is_checked(repo: Path) -> None:
    original = BASE + "\nfrom gigaverse.core.shared.tests.helpers import existing_fixture\n"
    write(repo, "conftest.py", original)
    commit(repo)
    write(repo, "conftest.py", original.replace("import existing_fixture", "import existing_fixture, customer_fixture"))
    assert check(repo).returncode == 1


@pytest.mark.parametrize(
    "addition",
    [
        "def pytest_runtest_setup(item): pass\n",
        "pytest_plugins.append('gigaverse.customer.plugin')\n",
        "pytest_plugins.extend(['gigaverse.customer.plugin'])\n",
    ],
)
def test_hooks_and_plugin_mutations_need_explanations(repo: Path, addition: str) -> None:
    write(repo, "conftest.py", BASE + "\n" + addition)
    assert check(repo).returncode == 1
    write(repo, "conftest.py", BASE + "\n" + REASON + addition)
    assert check(repo).returncode == 0


def test_activation_is_an_actual_comment_not_a_docstring(repo: Path) -> None:
    unmarked = BASE.replace(ACTIVATION, "")
    write(repo, "conftest.py", unmarked)
    commit(repo)
    source = '"""' + ACTIVATION + '"""\n' + unmarked + "\nclass InfrastructureValue: pass\n"
    write(repo, "conftest.py", source)
    assert check(repo).returncode == 0
    write(repo, "conftest.py", ACTIVATION + source)
    result = check(repo)
    assert result.returncode == 1
    assert "class InfrastructureValue" in result.stdout


def test_reverting_global_edit_restores_scoped_selection_without_local_hooks(repo: Path) -> None:
    write(repo, "tests/test_first.py", "def test_first(): assert 1 == 1\n")
    write(repo, "tests/test_second.py", "def test_second(): assert 2 == 2\n")
    base = commit(repo)
    write(repo, "conftest.py", BASE + "\n@pytest.fixture\ndef unnecessary_global(): pass\n")
    bad_head = commit(repo)  # No Git hooks installed: server preflight still rejects this.
    assert check(repo, "--base", base, "--head", bad_head).returncode == 1
    write(repo, "conftest.py", BASE)
    write(repo, "tests/test_first.py", "def test_first(): assert 3 == 3\n")
    repaired_head = commit(repo)
    assert check(repo, "--base", base, "--head", repaired_head).returncode == 0
    cache = GraphCache(repo / "impact.sqlite3")
    try:
        config = ImpactConfig(test_roots=["tests"])
        bad_plan = affected(repo, base, bad_head, config, cache)
        assert set(bad_plan.selected) == {"tests/test_first.py", "tests/test_second.py"}
        repaired_plan = affected(repo, base, repaired_head, config, cache)
        assert repaired_plan.changed == ["tests/test_first.py"]
        assert repaired_plan.selected == ["tests/test_first.py"]
    finally:
        cache.close()


@pytest.mark.parametrize(
    "import_line", ["from gv.ai.common.testing import plugin", "pytest_plugins = ['gv.ai.common.testing.plugin']"]
)
def test_src_layout_follows_relative_transitive_helpers(repo: Path, import_line: str) -> None:
    helper = "src/gv/ai/common/testing/nested.py"
    write(repo, "conftest.py", BASE + "\n" + import_line + "\n")
    write(repo, "src/gv/ai/common/testing/plugin.py", "from . import nested\n")
    write(repo, helper, "import pytest\n")
    base = commit(repo)
    write(repo, helper, "import pytest\n@pytest.fixture(autouse=True)\ndef unsafe(): pass\n")
    head = commit(repo)
    args = (
        "--module-root",
        "src",
        "--module-root",
        ".",
        "--project-import-prefix",
        "gv.ai",
        "--follow-import-prefix",
        "gv.ai.common.testing",
        "--base",
        base,
        "--head",
        head,
    )
    result = check(repo, *args)
    assert result.returncode == 1, result.stdout + result.stderr
    assert helper in result.stdout
    write(repo, helper, "import pytest\n" + REASON + "@pytest.fixture(autouse=True)\ndef unsafe(): pass\n")
    commit(repo)
    assert check(repo, *args[:-1], "HEAD").returncode == 0


def test_src_package_initializer_resolves_relative_imports(repo: Path) -> None:
    write(repo, "conftest.py", BASE + "\nimport gv.ai.common.testing\n")
    write(repo, "src/gv/ai/common/testing/__init__.py", "from . import cleanup\n")
    helper = "src/gv/ai/common/testing/cleanup.py"
    write(repo, helper, "import pytest\n")
    commit(repo)
    write(repo, helper, "import pytest\n@pytest.fixture\ndef unsafe(): pass\n")
    result = check(repo, "--module-root", "src", "--follow-import-prefix", "gv.ai.common.testing")
    assert result.returncode == 1, result.stdout + result.stderr
    assert helper in result.stdout


def test_ai_application_import_needs_reason_but_external_import_does_not(repo: Path) -> None:
    args = ("--module-root", "src", "--project-import-prefix", "gv.ai")
    write(repo, "conftest.py", BASE + "\nimport prefect\n")
    assert check(repo, *args).returncode == 0
    write(repo, "conftest.py", BASE + "\nfrom gv.ai.public_api_service.api import app\n")
    assert check(repo, *args).returncode == 1
    write(repo, "conftest.py", BASE + "\n" + REASON + "from gv.ai.public_api_service.api import app\n")
    assert check(repo, *args).returncode == 0


@pytest.mark.skipif(sys.platform == "win32", reason="Composite action uses POSIX shell; CLI contracts run on Windows")
@pytest.mark.parametrize("justified", [False, True])
def test_composite_executes_without_installed_package_and_propagates_failure(repo: Path, justified: bool) -> None:
    action_path = SCRIPT.parents[2] / ".github/actions/pytest-expansion"
    action = yaml.safe_load((action_path / "action.yml").read_text())
    assert len(action["runs"]["steps"]) == 1  # No second checkout, setup or install.
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "conftest.py", BASE + "\n" + (REASON if justified else "") + "@pytest.fixture\ndef addition(): pass\n")
    commit(repo)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", action["runs"]["steps"][0]["run"]],
        cwd=repo,
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(repo),
            "SHARED_ACTION_PATH": str(action_path),
            "EXPANSION_BASE": base,
            "EXPANSION_PYTHON": sys.executable,
            "EXPANSION_HEAD": "HEAD",
            "EXPANSION_MODULE_ROOTS": ".",
            "EXPANSION_PROJECT_PREFIXES": "gigaverse",
            "EXPANSION_FOLLOW_PREFIXES": "",
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == (0 if justified else 1), result.stdout + result.stderr
    assert ("EXPLAINED" if justified else "BLOCKED") in result.stdout


# --- Running as a pre-commit hook: hostile locale, and an inherited git environment -------------
#
# Both of these only bite when the check runs as a hook rather than in CI: pre-commit inherits the
# developer's locale (cp1252 on Windows) and, when the commit is made from a linked worktree, the
# GIT_DIR git exports to hooks.


NON_ASCII_SOURCE = ACTIVATION + "# reason: café — joined‍\n" + "import pytest\n"


def test_reads_utf8_sources_under_a_non_utf8_locale(repo: Path) -> None:
    """
    Source is UTF-8 by definition (PEP 3120); the locale must not get a vote.

    `Path.read_text()` with no encoding decodes with the locale default, which is cp1252 on
    Windows and ascii under LC_ALL=C. Byte 0x8d (from U+200D here) has no cp1252 mapping, so the
    hook died with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d` and blocked the
    commit outright.
    """
    (repo / "conftest.py").write_bytes(NON_ASCII_SOURCE.encode("utf-8"))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo",
            str(repo),
            "--project-import-prefix",
            "gigaverse",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            # Defeat Python's C-locale coercion and UTF-8 mode so the interpreter really does pick
            # a non-UTF-8 default; without this the test would be vacuous on Linux CI.
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONCOERCECLOCALE": "0",
            "PYTHONUTF8": "0",
        },
    )

    assert "UnicodeDecodeError" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def other_repo(tmp_path: Path) -> Path:
    root = tmp_path / "elsewhere"
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Other")
    git(root, "config", "user.email", "other@example.invalid")
    write(root, "marker.txt", "elsewhere\n")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "elsewhere")
    return root


def test_git_reads_the_requested_repo_despite_an_inherited_git_dir(
    repo: Path, other_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-C <root>` alone does not pin the repository — GIT_DIR outranks it."""
    monkeypatch.setenv("GIT_DIR", str(other_repo / ".git"))

    assert "test snapshot" in pytest_expansion.git(repo, "log", "-1", "--pretty=%s")


def test_inherited_git_dir_would_otherwise_redirect_the_command(
    repo: Path, other_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Characterises why the scrub exists, so the test above is not asserting a tautology."""
    monkeypatch.setenv("GIT_DIR", str(other_repo / ".git"))

    unscrubbed = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--pretty=%s"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert unscrubbed.stdout.strip() == "elsewhere"
