"""
Pin the test-file isolation checker's judgment.

The invariant it enforces — test modules never import test modules — is
what makes file-level CI test selection sound, so the checker must catch
every import shape that couples two test files while never flagging the
legitimate sharing routes (conftest fixtures, non-test helper modules,
production code whose name merely looks test-shaped).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from pytest_selective.hygiene import (
    assert_test_file_isolation,
    discover_test_modules,
    find_test_import_violations,
)

REPO_ROOT = Path(__file__).parents[2]


def _write(repo: Path, relative: str, content: str = "") -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for package in ("tests", "tests/test_alpha", "tests/test_beta", "tests/helpers"):
        _write(tmp_path, f"{package}/__init__.py")
    _write(tmp_path, "tests/test_alpha/test_core.py", "CORE = 1\n")
    _write(tmp_path, "tests/test_alpha/builders.py", "def build(): ...\n")
    _write(tmp_path, "tests/helpers/shared.py", "SHARED = 1\n")
    return tmp_path


def _violations(repo: Path) -> list[str]:
    return [violation.imported_module for violation in find_test_import_violations(repo, [Path("tests")])]


class TestViolationShapes:
    def test_absolute_import_of_a_test_module_is_flagged(self, repo: Path) -> None:
        _write(repo, "tests/test_beta/test_uses.py", "import tests.test_alpha.test_core\n")

        assert _violations(repo) == ["tests.test_alpha.test_core"]

    def test_from_import_binding_a_test_submodule_is_flagged(self, repo: Path) -> None:
        _write(repo, "tests/test_beta/test_uses.py", "from tests.test_alpha import test_core\n")

        assert _violations(repo) == ["tests.test_alpha.test_core"]

    def test_from_import_of_a_test_module_attribute_is_flagged(self, repo: Path) -> None:
        _write(repo, "tests/test_beta/test_uses.py", "from tests.test_alpha.test_core import CORE\n")

        assert _violations(repo) == ["tests.test_alpha.test_core"]

    def test_relative_import_of_a_sibling_test_module_is_flagged(self, repo: Path) -> None:
        _write(repo, "tests/test_alpha/test_uses.py", "from .test_core import CORE\n")

        assert _violations(repo) == ["tests.test_alpha.test_core"]

    def test_relative_parent_import_of_a_test_module_is_flagged(self, repo: Path) -> None:
        _write(repo, "tests/test_beta/test_uses.py", "from ..test_alpha.test_core import CORE\n")

        assert _violations(repo) == ["tests.test_alpha.test_core"]


class TestLegitimateSharing:
    def test_non_test_helper_inside_a_test_package_is_allowed(self, repo: Path) -> None:
        _write(repo, "tests/test_alpha/test_uses.py", "from tests.test_alpha.builders import build\n")

        assert _violations(repo) == []

    def test_shared_helper_package_is_allowed(self, repo: Path) -> None:
        _write(repo, "tests/test_beta/test_uses.py", "from tests.helpers.shared import SHARED\n")

        assert _violations(repo) == []

    def test_production_module_with_test_shaped_name_is_not_flagged(self, repo: Path) -> None:
        _write(repo, "tools/__init__.py")
        _write(repo, "tools/stress_test.py", "def run(): ...\n")
        _write(repo, "tests/test_beta/test_uses.py", "from tools.stress_test import run\n")

        assert _violations(repo) == []

    def test_unresolvable_imports_are_ignored(self, repo: Path) -> None:
        _write(repo, "tests/test_beta/test_uses.py", "import test_nonexistent_module\n")

        assert _violations(repo) == []


class TestReporting:
    def test_assert_helper_raises_with_every_violation_listed(self, repo: Path) -> None:
        _write(
            repo,
            "tests/test_beta/test_uses.py",
            "import tests.test_alpha.test_core\nfrom ..test_alpha.test_core import CORE\n",
        )

        with pytest.raises(AssertionError) as excinfo:
            assert_test_file_isolation(repo, [Path("tests")])

        message = str(excinfo.value)
        assert "tests.test_alpha.test_core" in message
        assert "conftest.py or a non-test helper module" in message

    def test_assert_helper_passes_on_a_clean_tree(self, repo: Path) -> None:
        assert_test_file_isolation(repo, [Path("tests")])

    def test_discovery_accepts_a_single_file_root(self, repo: Path) -> None:
        target = repo / "tests" / "test_alpha" / "test_core.py"

        assert discover_test_modules([target]) == [target]
        assert discover_test_modules([repo / "tests" / "test_alpha" / "builders.py"]) == []


def test_backend_common_tests_hold_the_isolation_invariant() -> None:
    """
    The repo's own suite complies: no test module imports another.

    This is the same call every consumer repo makes; keeping it green
    here is what lets file-level test selection trust the invariant
    everywhere.
    """
    assert_test_file_isolation(REPO_ROOT, [Path("tests")])


def test_repeated_imports_do_not_repeat_filesystem_probes(repo: Path) -> None:
    original_is_file = Path.is_file

    def scan_probe_count() -> tuple[int, int]:
        probes: list[Path] = []

        def is_file(path: Path) -> bool:
            probes.append(path)
            return original_is_file(path)

        with patch.object(Path, "is_file", is_file):
            violations = find_test_import_violations(repo, [Path("tests")])
        assert all(violation.imported_module == "tests.test_alpha.test_core" for violation in violations)
        return len(probes), len(violations)

    source = "import missing_external_package\nfrom tests.test_alpha.test_core import CORE\n"
    _write(repo, "tests/test_beta/test_uses_0.py", source)
    baseline_probes, baseline_violations = scan_probe_count()
    importer_count = 25
    for index in range(1, importer_count):
        _write(repo, f"tests/test_beta/test_uses_{index}.py", source)
    repeated_probes, repeated_violations = scan_probe_count()

    assert baseline_violations == 1
    assert repeated_violations == importer_count
    assert repeated_probes == baseline_probes


def test_separate_scans_observe_new_and_removed_import_targets(repo: Path) -> None:
    _write(repo, "tests/test_beta/test_uses.py", "import tests.test_alpha.test_added\n")
    assert _violations(repo) == []

    target = _write(repo, "tests/test_alpha/test_added.py")
    assert _violations(repo) == ["tests.test_alpha.test_added"]

    target.unlink()
    assert _violations(repo) == []


def test_symlink_aliases_are_judged_by_their_resolved_test_file(repo: Path) -> None:
    target = repo / "tests/test_alpha/test_core.py"
    (repo / "tests/helpers/alias.py").symlink_to(target)
    _write(repo, "tests/test_beta/test_uses.py", "from tests.helpers.alias import CORE\n")
    # A self import through an alias is still a self import.
    target.write_text("import tests.helpers.alias\n", encoding="utf-8")

    assert _violations(repo) == ["tests.helpers.alias"]


def test_module_file_precedes_package_with_the_same_import_name(repo: Path) -> None:
    target = repo / "tests/test_alpha/test_core.py"
    package = _write(repo, "tests/helpers/alias/__init__.py")
    package.unlink()
    package.symlink_to(target)
    plain_module = _write(repo, "tests/helpers/alias.py")
    _write(repo, "tests/test_beta/test_uses.py", "import tests.helpers.alias\n")

    assert _violations(repo) == []
    plain_module.unlink()
    assert _violations(repo) == ["tests.helpers.alias"]
