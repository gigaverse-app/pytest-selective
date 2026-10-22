"""
Compare the files tests actually read with what the dependency graph lets them reach.

The graph sees imports and declarations only. A test that reads a repository file as data, runs a
script or loads a module by path is invisible to selection unless the input is declared, and
nothing else notices the omission: the test simply stops running when that input changes. The
``impact_audit_plugin`` records each test file's reads during the selected run; this module fails
on every read the HEAD graph cannot reach from that test. A new test is always selected in the
change that adds it, so its reads are audited when it is introduced, including reads in helpers.
"""

from pathlib import Path

from pytest_selective.impact_declarations import match_inputs
from pytest_selective.impact_graph import matches, reachable
from pytest_selective.impact_models import (
    AuditExemption,
    AuditRecord,
    AuditReport,
    ImpactConfig,
    Snapshot,
    UndeclaredRead,
    file_of,
)

PLACEMENT_GUIDE = "docs/guides/test-dependency-placement.md"


def load_records(directory: Path) -> list[AuditRecord]:
    records = [AuditRecord.model_validate_json(path.read_bytes()) for path in sorted(directory.glob("*.json"))]
    if not records:
        raise ValueError(f"no audit records in {directory}; was pytest run with --impact-audit-dir?")
    return records


def _exempt_pairs(snapshot: Snapshot, exemptions: list[AuditExemption]) -> list[tuple[set[str], set[str]]]:
    # The declaration glob language, so a stale exemption is a hard error exactly like a stale declaration.
    files = set(snapshot.files)
    pairs: list[tuple[set[str], set[str]]] = []
    for index, exemption in enumerate(exemptions):
        location = f"{snapshot.tree}:audit_exemptions[{index}]"
        readers = set().union(*(match_inputs(pattern, files, location) for pattern in exemption.readers))
        inputs = set().union(*(match_inputs(pattern, files, location) for pattern in exemption.inputs))
        pairs.append((readers, inputs))
    return pairs


def audit(snapshot: Snapshot, records: list[AuditRecord], config: ImpactConfig) -> AuditReport:
    """Every recorded (test, input) pair the test's dependency closure does not contain."""
    exempt = _exempt_pairs(snapshot, config.audit_exemptions)
    reads: dict[str, set[str]] = {}
    for record in records:
        for test, paths in record.inputs.items():
            reads.setdefault(test, set()).update(paths)
    # Only the committed tree can be declared against: a file absent from HEAD has no edge to add.
    reads = {test: paths & snapshot.files.keys() for test, paths in reads.items() if test in snapshot.files}
    # An always-run test is selected by every change, so no input can skip it.
    always = {test for test in reads if matches(test, config.always_run)}
    undeclared: list[UndeclaredRead] = []
    exempted = 0
    for test, paths in sorted(reads.items()):
        # `@contents:` nodes are the non-transitive edges of content declarations.
        closure = {file_of(node) for node in reachable(snapshot.edges, {test})}
        for path in sorted(paths - closure):
            if test in always or any(test in readers and path in inputs for readers, inputs in exempt):
                exempted += 1
            else:
                undeclared.append(UndeclaredRead(test=test, input=path))
    return AuditReport(
        head=snapshot.tree,
        records=len(records),
        audited_tests=len(reads),
        recorded_reads=sum(len(paths) for paths in reads.values()),
        exempted_reads=exempted,
        undeclared=undeclared,
        recorder_errors=sorted({error for record in records for error in record.errors}),
    )


def summary(report: AuditReport) -> str:
    """Markdown for the GitHub step summary."""
    lines = [
        "### Test-impact read audit",
        "",
        f"{report.audited_tests} test files read {report.recorded_reads} tracked files "
        f"({report.exempted_reads} exempted or always-run) across {report.records} pytest processes; "
        f"{len(report.undeclared)} reads are unreachable in the dependency graph.",
    ]
    if report.undeclared:
        lines += [
            "",
            "A change to an undeclared input selects none of its readers. Declare each input on the file "
            "that reads it: `# gv:test-dependency: <path>` for an import edge, or a "
            "`<file>.gv-dependency.yaml` sidecar with `kind: content` for a file read as text. "
            f"See `{PLACEMENT_GUIDE}`. Inputs another lane covers belong in `audit_exemptions`.",
            "",
            "| Test file | Undeclared input |",
            "| --- | --- |",
            *(f"| `{read.test}` | `{read.input}` |" for read in report.undeclared),
        ]
    if report.recorder_errors:
        lines += ["", "Recorder errors (the reads these events carried were not audited):", ""]
        lines += [f"- `{error}`" for error in report.recorder_errors]
    return "\n".join(lines) + "\n"
