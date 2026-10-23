"""Plugin registration is session-wide, even when a test module declares it."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_selective.impact_graph import GraphCache, parse_source
from pytest_selective.impact_models import ImpactConfig
from pytest_selective.impact_selection import affected
from pytest_selective.pytest_sharding import plan_shards
from tests.testing.git_repo import commit, init, write


@pytest.mark.parametrize(
    "declaration",
    [
        'pytest_plugins = "support"',
        'pytest_plugins = "support,other"',
        'pytest_plugins: list[str] = ["support"]',
        'pytest_plugins = []\npytest_plugins += ["support"]',
        'pytest_plugins = []\npytest_plugins.append("support")',
        'pytest_plugins = []\npytest_plugins.extend(("support",))',
        'if True:\n    pytest_plugins = ["support"]',
    ],
)
@pytest.mark.parametrize("owner", ["conftest.py", "tests/test_a.py"])
def test_registered_plugin_dependency_reaches_every_test(tmp_path: Path, declaration: str, owner: str) -> None:
    repo = tmp_path / "repo"
    init(repo)
    write(repo, "plugin_state.py", "VALUE = 1\n")
    write(
        repo,
        "support.py",
        "import pytest\nfrom plugin_state import VALUE\n"
        "@pytest.fixture(autouse=True)\ndef check_value(): assert VALUE == 1\n",
    )
    write(repo, "other.py")
    write(repo, "tests/test_a.py", "def test_a(): pass\n")
    write(repo, "tests/test_b.py", "def test_b(): pass\n")
    write(repo, owner, declaration + ("\ndef test_a(): pass\n" if owner.endswith("test_a.py") else "\n"))
    base = commit(repo)
    # Exercise pytest itself: the plugin registered by test_a also changes test_b.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(repo))
    command = [sys.executable, "-m", "pytest", "-q", "-c", "", "tests/test_a.py", "tests/test_b.py"]
    assert subprocess.run(command, cwd=repo, env=env, capture_output=True).returncode == 0
    write(repo, "plugin_state.py", "VALUE = 2\n")
    head = commit(repo)
    failed = subprocess.run(command, cwd=repo, env=env, capture_output=True, text=True)
    assert failed.returncode == 1 and "2 errors" in failed.stdout, failed.stdout + failed.stderr
    cache = GraphCache(tmp_path / "cache.db")
    try:
        report = affected(repo, base, head, ImpactConfig(test_roots=["tests"]), cache)
        assert report.selected == ["tests/test_a.py", "tests/test_b.py"]
    finally:
        cache.close()


def test_selected_files_keep_the_test_module_that_registers_their_plugin(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init(repo)
    write(repo, "support.py", "import pytest\n@pytest.fixture\ndef shared(): return 1\n")
    write(repo, "tests/test_a.py", 'pytest_plugins = "support"\ndef test_a(): pass\n')
    write(repo, "tests/test_b.py", "def test_b(shared): assert shared == 1\n")
    write(repo, "tests/test_c.py", "def test_c(): pass\n")
    base = commit(repo)
    write(repo, "tests/test_b.py", "def test_b(shared): assert shared > 0\n")
    head = commit(repo)
    cache = GraphCache(tmp_path / "cache.db")
    try:
        report = affected(repo, base, head, ImpactConfig(test_roots=["tests"]), cache)
        assert report.selected == ["tests/test_a.py", "tests/test_b.py"]
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(repo))
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *report.selected], cwd=repo, env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        cache.close()


@pytest.mark.parametrize("change", ["dependency", "remove-registration", "unrelated"])
def test_recursive_plugin_registration_and_base_edges(tmp_path: Path, change: str) -> None:
    repo = tmp_path / "repo"
    init(repo)
    write(repo, "conftest.py", 'pytest_plugins = "support"\n')
    write(repo, "support.py", 'pytest_plugins = "nested"\n')
    write(repo, "nested.py", "import dependency\n")
    write(repo, "dependency.py", "VALUE = 1\n")
    write(repo, "unrelated.py", "VALUE = 1\n")
    write(repo, "tests/test_a.py", "def test_a(): pass\n")
    base = commit(repo)
    if change == "remove-registration":
        write(repo, "support.py", "")
    else:
        write(repo, f"{change}.py", "VALUE = 2\n")
    head = commit(repo)
    cache = GraphCache(tmp_path / "cache.db")
    try:
        report = affected(repo, base, head, ImpactConfig(test_roots=["tests"]), cache)
        assert report.selected == ([] if change == "unrelated" else ["tests/test_a.py"])
    finally:
        cache.close()


@pytest.mark.parametrize(
    "source, expected",
    [
        ('pytest_plugins = "sup" + "port"', ["support"]),
        ('pytest_plugins = ["support"] + ["other"]', ["other", "support"]),
        ('pytest_plugins = ["support,other"]', ["support,other"]),
        ("pytest_plugins = None", []),
        ('def helper():\n    pytest_plugins = ["unused"]', []),
        ('class Example:\n    pytest_plugins = ["unused"]', []),
        ("pytest_plugins = get_plugins()", None),
        ('pytest_plugins = ["support", dynamic]', None),
        ("from settings import pytest_plugins", None),
        ("pytest_plugins = []\npytest_plugins.extend(dynamic)", None),
        ("pytest_plugins = []\npytest_plugins[:] = [dynamic]", None),
        ('pytest_plugins, other = (["support"], 1)', None),
        ('pytest_plugins = []\nplugins = pytest_plugins\nplugins.append("support")', None),
    ],
)
def test_static_plugin_declarations(source: str, expected: list[str] | None) -> None:
    assert parse_source(source.encode()).registered_plugins == expected


def test_computed_registered_plugins_cannot_prove_selection(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init(repo)
    write(repo, "conftest.py", "pytest_plugins = plugin_names()\n")
    write(repo, "tests/test_a.py", "def test_a(): pass\n")
    revision = commit(repo)
    cache = GraphCache(tmp_path / "cache.db")
    try:
        with pytest.raises(ValueError, match="cannot statically resolve pytest_plugins"):
            affected(repo, revision, revision, ImpactConfig(test_roots=["tests"]), cache)
    finally:
        cache.close()


@pytest.mark.parametrize("exact_files", [False, True])
def test_shards_keep_test_module_plugin_registration_in_the_same_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exact_files: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    write(tmp_path, "support.py", "import pytest\n@pytest.fixture\ndef shared(): return 1\n")
    write(tmp_path, "tests/test_a.py", 'pytest_plugins = "support"\ndef test_a(): pass\n')
    write(tmp_path, "tests/test_b.py", "def test_b(shared): assert shared == 1\n")
    shards = plan_shards({}, [Path("tests")], 2, exact_files=exact_files)
    # Each nonempty manifest is an independent pytest process, as in CI-esta.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONPATH=str(tmp_path))
    for shard in shards:
        if not shard.paths:
            continue
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *shard.paths], env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path for shard in shards for path in shard.paths) == ["tests/test_a.py", "tests/test_b.py"]
