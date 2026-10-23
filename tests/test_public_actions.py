"""One implementation per action; the root default forwards its complete contract."""

# gv:test-dependency: action.yml
# gv:test-dependency: actions/*/action.yml

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "actions").glob("*/action.yml"))


@pytest.mark.parametrize("source", SOURCES, ids=lambda p: p.parent.name)
def test_named_action_is_the_implementation_without_duplicate_aliases(source):
    action = yaml.safe_load(source.read_text())
    assert not (ROOT / source.parent.name / "action.yml").exists()
    assert not (ROOT / ".github/actions").exists()
    assert not any(step.get("uses", "").startswith("$/") for step in action["runs"]["steps"])


def test_root_action_forwards_the_complete_contract_at_the_same_revision():
    original = yaml.safe_load((ROOT / "actions" / "test-impact" / "action.yml").read_text())
    public = yaml.safe_load((ROOT / "action.yml").read_text())
    assert public.get("inputs", {}) == original.get("inputs", {})
    assert public["runs"]["using"] == "composite"
    (step,) = public["runs"]["steps"]
    assert step["uses"] == "$/actions/test-impact"
    assert step.get("with", {}) == {key: "${{ inputs." + key + " }}" for key in original.get("inputs", {})}
    assert public.get("outputs", {}) == {
        key: {"description": value["description"], "value": "${{ steps.action.outputs." + key + " }}"}
        for key, value in original.get("outputs", {}).items()
    }
