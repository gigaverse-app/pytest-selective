"""Parse dependency declarations without pytest, Git, caches or language analysis.

Callers provide tracked paths and manifest bytes, then combine the returned edges
with their language's import graph. Content nodes are leaves, not executable imports.
"""

from collections.abc import Collection, Mapping

from .models import (
    CONTENTS_PREFIX,
    DependencyInputs,
    DependencyManifest,
    ManifestDependencyRule,
    contents_node,
    file_of,
)
from .parser import (
    DIRECTORY_MANIFEST,
    SIDECAR_SUFFIX,
    DependencyDeclarationError,
    is_declaration,
    manifest_edges,
    match_inputs,
    parse_manifest,
)

__all__ = [
    "CONTENTS_PREFIX",
    "DIRECTORY_MANIFEST",
    "SIDECAR_SUFFIX",
    "DependencyDeclarationError",
    "DependencyInputs",
    "DependencyManifest",
    "ManifestDependencyRule",
    "contents_node",
    "dependency_edges",
    "file_of",
    "is_declaration",
    "manifest_edges",
    "match_inputs",
    "parse_manifest",
]


def dependency_edges(
    manifests: Mapping[str, bytes], files: Collection[str], *, revision: str = "inputs"
) -> dict[str, set[str]]:
    """Validated reader-to-input edges from one consistent repository snapshot.

    ``files`` includes every tracked file, including declarations. ``manifests``
    supplies the bytes of every declaration in that inventory. Missing bytes,
    invalid patterns and patterns matching no files are authoring errors.
    No files are opened, Git commands run, or Python modules analyzed here.
    """
    inventory = set(files)
    expected = {path for path in inventory if is_declaration(path)}
    if set(manifests) != expected:
        raise DependencyDeclarationError(
            f"{revision}: declaration inventory mismatch; missing {sorted(expected - set(manifests))}, "
            f"unexpected {sorted(set(manifests) - expected)}"
        )
    edges: dict[str, set[str]] = {}
    for path, source in sorted(manifests.items()):
        for reader, inputs in manifest_edges(path, source, revision, inventory).items():
            edges.setdefault(reader, set()).update(inputs)
    return edges
