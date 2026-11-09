"""Record which repository files pytest actually imports or opens while collecting each test file.

The contract's runtime referee: an independent check of the planner's static analysis. Run as
``python -I -B runtime_deps.py TREE TEST...`` (``-B``: write no bytecode into TREE). For each test file it runs pytest's collection in this
process, then prints, as JSON, every file under TREE that was imported or opened along the way.
Modules and sys.path are restored between test files, so each file's dependencies are its own.
"""

import json
import os
import sys
from functools import cache
from pathlib import Path

import pytest


@cache
def _under(root: Path, path: str | None) -> str | None:
    # Each process inspects one immutable exported tree. Cache path resolution,
    # never the per-test import/open observations, which remain isolated below.
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def main(tree: str, tests: list[str]) -> dict[str, list[str]]:
    root = Path(tree).resolve()
    opened: set[str] = set()

    def audit(event: str, args: tuple) -> None:
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            opened.add(os.fsdecode(args[0]))

    sys.addaudithook(audit)
    os.chdir(root)
    # As `python -m pytest` from the repository root.
    sys.path.insert(0, str(root))
    modules, path = set(sys.modules), list(sys.path)
    found: dict[str, list[str]] = {}
    for test in tests:
        opened.clear()
        pytest.main(["--collect-only", "-q", "-p", "no:cacheprovider", test])
        loaded = {getattr(module, "__file__", None) for module in list(sys.modules.values())}
        files = {relative for item in loaded | opened if (relative := _under(root, item))}
        found[test] = sorted(file for file in files if "__pycache__" not in file.split("/"))
        for name in set(sys.modules) - modules:
            del sys.modules[name]
        sys.path[:] = path
    return found


if __name__ == "__main__":
    result = main(sys.argv[1], sys.argv[2:])
    sys.stdout.write("\nRUNTIME_DEPS " + json.dumps(result) + "\n")
