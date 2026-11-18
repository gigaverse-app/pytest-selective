"""Every name the supported-API page lists stays importable, so adopters cannot break silently."""

import importlib
import re
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "docs/python-api.md"
ROW = re.compile(r"^\| `(pytest_selective[\w.]*)` \| (.+) \|$", re.MULTILINE)


def _names() -> list[tuple[str, str]]:
    rows = ROW.findall(PAGE.read_text(encoding="utf-8"))
    assert rows, "the supported-API page lists no modules"
    return [(module, name) for module, cell in rows for name in re.findall(r"`(\w+)`", cell)]


@pytest.mark.parametrize(("module", "name"), _names())
def test_supported_name_is_importable(module: str, name: str) -> None:
    assert hasattr(importlib.import_module(module), name), f"{module}.{name} is listed in docs/python-api.md"
