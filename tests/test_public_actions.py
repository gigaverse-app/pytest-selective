"""Public action paths preserve inputs, outputs and the caller-pinned implementation."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / ".github/actions").glob("*/action.yml"))


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.parent.name)
def test_public_action_forwards_the_complete_contract_at_the_same_revision(source):
    original = yaml.safe_load(source.read_text())
    public = yaml.safe_load((ROOT / source.parent.name / "action.yml").read_text())
    assert public.get("inputs", {}) == original.get("inputs", {})
    assert public["runs"]["using"] == "composite"
    (step,) = public["runs"]["steps"]
    assert step["uses"] == "$/" + source.parent.relative_to(ROOT).as_posix()
    assert step.get("with", {}) == {key: "${{ inputs." + key + " }}" for key in original.get("inputs", {})}
    assert public.get("outputs", {}) == {
        key: {"description": value["description"], "value": "${{ steps.action.outputs." + key + " }}"}
        for key, value in original.get("outputs", {}).items()
    }


def test_root_action_is_the_primary_public_entry_point():
    assert yaml.safe_load((ROOT / "action.yml").read_text()) == yaml.safe_load(
        (ROOT / "test-impact" / "action.yml").read_text()
    )
