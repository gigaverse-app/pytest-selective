"""Compatibility exports; portable declaration semantics live in one package."""

from selective_deps import (
    DIRECTORY_MANIFEST,
    SIDECAR_SUFFIX,
    DependencyDeclarationError,
    is_declaration,
    manifest_edges,
    match_inputs,
    parse_manifest,
)

__all__ = [
    "DIRECTORY_MANIFEST",
    "SIDECAR_SUFFIX",
    "DependencyDeclarationError",
    "is_declaration",
    "manifest_edges",
    "match_inputs",
    "parse_manifest",
]
