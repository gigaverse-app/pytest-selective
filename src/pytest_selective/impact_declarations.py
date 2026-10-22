"""Reader-owned declarations: one path language and one YAML rule boundary."""

import re
from pathlib import PurePosixPath

import yaml

from pytest_selective.impact_models import DependencyManifest, contents_node

SIDECAR_SUFFIX = ".gv-dependency.yaml"
DIRECTORY_MANIFEST = ".gv-dependencies.yaml"


class DependencyDeclarationError(ValueError):
    """An authoring error which must never become a successful full fallback."""


def is_declaration(path: str) -> bool:
    return path.endswith(SIDECAR_SUFFIX) or PurePosixPath(path).name == DIRECTORY_MANIFEST


def _path_pattern(pattern: str) -> re.Pattern[str]:
    """Compile our validated *, ?, ** language on every supported Python.

    A slash is never matched by an ordinary wildcard; a whole ** segment can
    consume zero or more directories. Hidden files are ordinary tracked inputs.
    """
    segments = pattern.split("/")
    expression = ""
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            expression += ".*" if last else "(?:[^/]+/)*"
        else:
            expression += "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in segment)
            if not last:
                expression += "/"
    return re.compile(expression, re.DOTALL)


def match_inputs(pattern: str, files: set[str], location: str, directory: str = ".") -> set[str]:
    parts = pattern.split("/")
    if (
        any(part in {"", ".", ".."} for part in parts)
        or any(char in pattern for char in "\\:[]{}")
        or any("**" in part and part != "**" for part in parts)
    ):
        raise DependencyDeclarationError(f"{location}: invalid repository-relative dependency pattern {pattern!r}")
    rooted = pattern if directory == "." else f"{directory}/{pattern}"
    matcher = _path_pattern(rooted)
    targets = {path for path in files if matcher.fullmatch(path)}
    if not targets:
        raise DependencyDeclarationError(f"{location}: test dependency {pattern!r} matches no tracked files")
    return targets


def _check_yaml_keys(node: yaml.Node, seen: set[int]) -> None:
    # Reject aliases and duplicate keys: neither may silently hide a rule.
    if id(node) in seen:
        raise DependencyDeclarationError("YAML aliases are not supported")
    seen.add(id(node))
    if isinstance(node, yaml.MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode) or key.tag != "tag:yaml.org,2002:str" or key.value in keys:
                raise DependencyDeclarationError(f"line {key.start_mark.line + 1}: duplicate or non-string YAML key")
            keys.add(key.value)
            _check_yaml_keys(value, seen)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            _check_yaml_keys(child, seen)


def parse_manifest(source: bytes, location: str) -> DependencyManifest:
    try:
        node = yaml.compose(source.decode("utf-8-sig"), Loader=yaml.SafeLoader)
        if node is not None:
            _check_yaml_keys(node, set())
        return DependencyManifest.model_validate(yaml.safe_load(source))
    except (ValueError, yaml.YAMLError) as error:
        raise DependencyDeclarationError(f"{location}: {error}") from error


def manifest_edges(path: str, source: bytes, tree: str, files: set[str]) -> dict[str, set[str]]:
    location = f"{tree}:{path}"
    is_directory = PurePosixPath(path).name == DIRECTORY_MANIFEST
    owner = path.removesuffix(SIDECAR_SUFFIX)
    if not is_directory and (owner not in files or is_declaration(owner)):
        raise DependencyDeclarationError(f"{location}: sidecar must belong to an existing non-sidecar tracked file")
    manifest = parse_manifest(source, location)
    directory = str(PurePosixPath(path).parent)
    reader_files = {file for file in files if not is_declaration(file)}
    edges: dict[str, set[str]] = {} if is_directory else {owner: {path}}
    for index, rule in enumerate(manifest.dependencies, 1):
        rule_location = f"{location}:rule {index}"
        if is_directory and not rule.readers:
            raise DependencyDeclarationError(f"{rule_location}: directory rule requires readers")
        if not is_directory and "readers" in rule.model_fields_set:
            raise DependencyDeclarationError(f"{rule_location}: file sidecar must not specify readers")
        readers = {owner}
        if is_directory:
            assert rule.readers is not None
            readers = _expand(rule.readers, reader_files, directory, rule_location)
        inputs = _expand(rule.inputs, files, directory, rule_location)
        for reader in readers:
            dependencies = inputs if rule.kind == "import" else {contents_node(target) for target in inputs}
            edges.setdefault(reader, set()).update(dependencies | {path})
            edges[reader].discard(reader)
    return edges


def _expand(patterns: list[str], files: set[str], directory: str, location: str) -> set[str]:
    targets: set[str] = set()
    for pattern in patterns:
        targets.update(
            match_inputs(
                pattern[2:] if pattern.startswith("//") else pattern,
                files,
                location,
                "." if pattern.startswith("//") else directory,
            )
        )
    return targets
