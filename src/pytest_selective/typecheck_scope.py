"""
Scope a type check to the files a change can affect, from the test-impact import graph.

A checker's verdict on a file depends only on that file, the files it imports transitively,
and global inputs: its configuration, stubs, installed packages, and modules resolved from
paths the graph does not model. So from a base that is known to check clean, a file can gain
a diagnostic only if its import closure contains a change. The scope is every checked file
whose closure, in the base or the head graph, reaches a changed file.

Anything the graph cannot vouch for widens to the full check: a changed global input, a
checker pattern this module cannot interpret, or a scope so large that listing it costs as
much as checking everything.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from pytest_selective.impact_graph import (
    GraphCache,
    changed_paths,
    matches,
    reachable,
    reverse_edges,
    seed_nodes,
    union_edges,
)
from pytest_selective.impact_models import ImpactConfig

CHECKABLE = (".py",)
UNSUPPORTED_GLOB = set("*?[")


class UnsupportedPattern(Exception):  # noqa: N818 - raised through pydantic, which would wrap a ValueError
    """A checker include/exclude pattern whose semantics this module does not reproduce."""


class PyrightSelection(BaseModel):
    """
    Which files a pyright-family checker checks, for the pattern shapes this module supports.

    Supported: path prefixes (a directory includes everything beneath it, a file itself) and
    `**/segment` excludes (any path segment). Any other glob is refused rather than guessed:
    a wrong guess could drop a file the checker would have checked.
    """

    include: list[str]
    exclude: list[str]

    def model_post_init(self, _context: object) -> None:
        for pattern in (*self.include, *self.exclude):
            body = pattern.removeprefix("**/") if pattern.startswith("**/") else pattern
            if UNSUPPORTED_GLOB & set(body):
                raise UnsupportedPattern(pattern)

    def checks(self, path: str) -> bool:
        return any(_under(path, root) for root in self.include) and not any(
            path.split("/").count(pattern[3:]) if pattern.startswith("**/") else _under(path, pattern)
            for pattern in self.exclude
        )


def _under(path: str, root: str) -> bool:
    root = root.rstrip("/")
    return path == root or path.startswith(root + "/")


class TypecheckScope(BaseModel):
    """`scoped`: check `files`; `full`: check everything; `none`: nothing checked can have changed."""

    mode: Literal["scoped", "full", "none"]
    files: list[str]
    reason: str


def scope(
    repo: Path,
    base: str,
    head: str,
    config: ImpactConfig,
    cache: GraphCache,
    checker_config: str,
    global_inputs: list[str],
    max_fraction: float,
) -> TypecheckScope:
    """The files to type-check at `head`, given that `base` checked clean under the same checker."""
    import json

    before = cache.snapshot(repo, base, config)
    after = cache.snapshot(repo, head, config)
    changed = changed_paths(before, after)
    if global_changes := [path for path in changed if path == checker_config or matches(path, global_inputs)]:
        return TypecheckScope(mode="full", files=[], reason=f"global inputs changed: {', '.join(global_changes[:5])}")
    settings = json.loads((repo / checker_config).read_text(encoding="utf-8"))
    try:
        selection = PyrightSelection(include=settings.get("include", ["."]), exclude=settings.get("exclude", []))
    except UnsupportedPattern as error:
        return TypecheckScope(mode="full", files=[], reason=f"unsupported checker pattern: {error}")
    affected = reachable(reverse_edges(union_edges(before, after)), seed_nodes(changed))
    checked = sorted(path for path in after.files if path.endswith(CHECKABLE) and selection.checks(path))
    files = [path for path in checked if path in affected]
    if not files:
        return TypecheckScope(mode="none", files=[], reason="no checked file reaches a change")
    if len(files) >= max_fraction * len(checked):
        return TypecheckScope(
            mode="full", files=[], reason=f"{len(files)} of the checked files ({len(checked)}) reach a change"
        )
    return TypecheckScope(
        mode="scoped", files=files, reason=f"{len(files)} of {len(checked)} checked files reach a change"
    )
