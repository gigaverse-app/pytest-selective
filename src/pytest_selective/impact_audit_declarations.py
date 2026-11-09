"""
Write the declarations a read audit finds missing, as one sidecar per reading test file.

``pytest-selective audit --write-declarations`` turns each undeclared ``test -> input`` read into a
rule in ``<test>.gv-dependency.yaml``, the reader-owned form that states the edge's kind. A Python
input becomes an ``import`` rule, because a test that loads or runs a script outside its imports
(often in a subprocess) also depends on what that script imports. Any other input becomes a
``content`` rule. Reads under one directory collapse into ``<directory>/**`` only when the test read
every tracked file under it, so the glob claims no input the run did not see. Every pattern is
checked against the analysed tree before anything is written.
"""

import json
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from pytest_selective.impact_audit import tracked_reads
from pytest_selective.impact_declarations import (
    SIDECAR_SUFFIX,
    DependencyDeclarationError,
    match_inputs,
    parse_manifest,
)
from pytest_selective.impact_models import (
    AuditRecord,
    AuditReport,
    ImpactModel,
    ManifestDependencyRule,
    Snapshot,
)

CONTENT_REASON = "Read at runtime; recorded by pytest-selective audit --write-declarations."
IMPORT_REASON = "Loaded or run outside the test's imports; recorded by pytest-selective audit --write-declarations."


class SidecarDeclarations(ImpactModel):
    """The rules one test file's sidecar gains, and the reads each pattern stands for."""

    test: str
    rules: list[ManifestDependencyRule]
    #: Pattern (as written, ``//``-rooted) to the undeclared reads it declares.
    covers: dict[str, list[str]]

    @property
    def sidecar(self) -> str:
        return self.test + SIDECAR_SUFFIX


class DeclarationPlan(ImpactModel):
    sidecars: list[SidecarDeclarations]
    #: Reads no valid pattern can name (the path itself is not a valid declaration), with the reason.
    skipped: list[str]


def _parents(path: str) -> Iterable[str]:
    """Each directory above ``path``, nearest first, never the repository root."""
    for parent in PurePosixPath(path).parents:
        if parent.as_posix() != ".":
            yield parent.as_posix()


def _patterns(undeclared: set[str], read: set[str], files: set[str]) -> dict[str, set[str]]:
    """Group undeclared reads into patterns: a directory glob only when the test read all of it."""
    patterns: dict[str, set[str]] = {}
    for path in sorted(undeclared):
        widest = None
        for directory in _parents(path):
            under = {file for file in files if file.startswith(directory + "/")}
            if not under <= read:
                # Every directory further up holds this one, so it cannot be fully read either.
                break
            if len(under & undeclared) > 1:
                widest = directory
        pattern = f"{widest}/**" if widest else path
        patterns.setdefault(pattern, set()).add(path)
    # Whether a directory qualifies does not depend on which read reached it, and every directory
    # below a qualifying one is fully read too, so all reads under a glob chose that same glob.
    return patterns


def plan_declarations(report: AuditReport, snapshot: Snapshot, records: list[AuditRecord]) -> DeclarationPlan:
    """The sidecar rules that would declare every undeclared read in ``report``."""
    files = set(snapshot.files)
    reads = tracked_reads(snapshot, records)
    undeclared: dict[str, set[str]] = {}
    for read in report.undeclared:
        undeclared.setdefault(read.test, set()).add(read.input)
    sidecars: list[SidecarDeclarations] = []
    skipped: list[str] = []
    for test, paths in sorted(undeclared.items()):
        inputs: dict[str, list[str]] = {"content": [], "import": []}
        covers: dict[str, list[str]] = {}
        for pattern, covered in sorted(_patterns(paths, reads[test], files).items()):
            try:
                # Never write a declaration that matches no tracked file at the analysed tree.
                matched = match_inputs(pattern, files, f"{snapshot.tree}:{test}{SIDECAR_SUFFIX}")
            except DependencyDeclarationError as error:
                skipped.extend(f"{test} -> {path}: {error}" for path in sorted(covered))
                continue
            kind = "import" if any(path.endswith(".py") for path in matched) else "content"
            inputs[kind].append(f"//{pattern}")
            covers[f"//{pattern}"] = sorted(covered)
        rules = [
            ManifestDependencyRule(inputs=patterns, kind=kind, reason=reason)
            for kind, reason in (("content", CONTENT_REASON), ("import", IMPORT_REASON))
            if (patterns := inputs[kind])
        ]
        if rules:
            sidecars.append(SidecarDeclarations(test=test, rules=rules, covers=covers))
    return DeclarationPlan(sidecars=sidecars, skipped=skipped)


def render_rules(rules: list[ManifestDependencyRule]) -> str:
    """Rules as items of a sidecar's ``dependencies`` list, every scalar quoted."""
    lines: list[str] = []
    for rule in rules:
        lines.append("  - inputs:")
        lines += [f"      - {json.dumps(pattern)}" for pattern in rule.inputs]
        lines.append(f"    kind: {rule.kind}")
        lines.append(f"    reason: {json.dumps(rule.reason)}")
    return "\n".join(lines) + "\n"


def write_sidecar(repo: Path, declarations: SidecarDeclarations) -> None:
    """Create the test's sidecar, or append the rules to the one it already has."""
    path = repo / declarations.sidecar
    rendered = render_rules(declarations.rules)
    if not path.exists():
        # LF on every platform: the sidecar is committed beside the test.
        text = "dependencies:\n" + rendered
        parse_manifest(text.encode(), declarations.sidecar)
    else:
        existing = path.read_bytes().decode("utf-8-sig")
        before = parse_manifest(existing.encode(), declarations.sidecar).dependencies
        newline = "\r\n" if "\r\n" in existing else "\n"
        text = existing + ("" if existing.endswith("\n") else newline) + rendered.replace("\n", newline)
        # Appending is textual so the file keeps its comments; prove it parses to exactly the old
        # rules plus the new ones, or leave the file untouched.
        try:
            appended = parse_manifest(text.encode(), declarations.sidecar).dependencies == before + declarations.rules
        except DependencyDeclarationError:
            appended = False
        if not appended:
            raise DependencyDeclarationError(
                f"{declarations.sidecar}: cannot append to this sidecar's layout; add these rules by hand:\n{rendered}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())
