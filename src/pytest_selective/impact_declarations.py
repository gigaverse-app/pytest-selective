"""Compatibility exports; portable declaration semantics live in one package."""

from pytest_selective_declarations import (
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
