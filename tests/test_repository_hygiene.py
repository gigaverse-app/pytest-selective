"""The selector's own test modules obey its file-isolation assumption."""

from pathlib import Path

from pytest_selective.hygiene import assert_test_file_isolation


def test_repository_test_files_are_independent() -> None:
    assert_test_file_isolation(Path(__file__).resolve().parents[1], [Path("tests")])
