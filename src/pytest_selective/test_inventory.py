"""
Canonical pytest test-module discovery.
"""

import fnmatch
from pathlib import Path

TEST_FILE_PATTERNS = ("test_*.py", "*_test.py", "*_tests.py", "tests.py")

DEFAULT_TEST_FILE_PATTERNS = TEST_FILE_PATTERNS


def is_test_file(path: Path, patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS) -> bool:
    """
    Return whether a path follows one configured pytest module convention.
    """
    return path.is_file() and any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)


def discover_test_files(
    test_roots: list[Path],
    patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS,
) -> set[Path]:
    """
    Discover configured test modules below directories or explicit files.
    """
    discovered: set[Path] = set()
    for root in test_roots:
        if root.is_file():
            if is_test_file(root, patterns):
                discovered.add(root)
            continue
        for pattern in patterns:
            discovered.update(path for path in root.rglob(pattern) if "__pycache__" not in path.parts)
    return discovered


def is_test_module_name(basename: str) -> bool:
    return any(fnmatch.fnmatch(basename, pattern) for pattern in TEST_FILE_PATTERNS)
