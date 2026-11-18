"""`pytest-selective declarations`: declarations to delete and sidecars to merge, from one graph build."""

from pathlib import Path

from pydantic import BaseModel
from selective_deps import crowded_sidecars

from pytest_selective.impact_graph import declared_edges, reachable
from pytest_selective.impact_models import Snapshot

GUIDE = "https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/sidecar-dependencies/"


class DeclarationHealth(BaseModel):
    #: Declared readers that no test file reaches: their declarations cannot change any selection.
    unreached: list[str]
    #: Directory to its file sidecars, where one `.gv-dependencies.yaml` can replace several.
    crowded: dict[str, list[str]]


def declaration_health(repo: Path, snapshot: Snapshot) -> DeclarationHealth:
    readers = set(declared_edges(repo, snapshot.tree, snapshot.files))
    reached = reachable(snapshot.edges, set(snapshot.tests))
    return DeclarationHealth(unreached=sorted(readers - reached), crowded=crowded_sidecars(snapshot.files))


def render(health: DeclarationHealth) -> str:
    sections: list[str] = []
    if health.unreached:
        sections.append(
            "Declared readers no test reaches: these declarations change no selection; delete them.\n"
            + "\n".join(f"  {path}" for path in health.unreached)
        )
    if health.crowded:
        sections.append(
            "Directories with several sidecars: merge each into one <directory>/.gv-dependencies.yaml.\n"
            + "\n".join(f"  {directory}/ ({len(paths)} sidecars)" for directory, paths in health.crowded.items())
        )
    if not sections:
        return "Declarations are tidy: every declared reader is reached and each directory has one manifest."
    return "\n\n".join([*sections, f"Authoring rules: {GUIDE}"])
