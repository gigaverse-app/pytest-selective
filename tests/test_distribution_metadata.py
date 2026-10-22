"""Distribution descriptions preserve real Markdown, including UTF-8 text."""

import pytest

from scripts.check_metadata import check_metadata


def test_utf8_description_round_trips() -> None:
    readme = "# Tests\n\nREADME → wheel · sdist\n"
    raw = f"Name: pytest-selective\nDescription-Content-Type: text/markdown\n\n{readme}".encode()
    check_metadata(raw, readme)


def test_stale_description_fails() -> None:
    raw = b"Name: pytest-selective\nDescription-Content-Type: text/markdown\n\nOld README\n"
    with pytest.raises(AssertionError, match="description differs"):
        check_metadata(raw, "Current README")
