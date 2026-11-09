"""Derive file selection from the repository graph and the execution inputs that run every selected test file.

CI-esta plans the lanes from .github/test-lanes.json, which extends the workflow and has no complete graph;
file selection inside the tests lane reads the complete lane file this repository's own plan-lanes smoke uses.
"""
# gv:test-dependency: .github/plan-lanes.json

import sys
from pathlib import Path

from pytest_selective.ci import LaneConfig

file_config = LaneConfig.file_config


if __name__ == "__main__":
    lanes = LaneConfig.model_validate_json(Path(".github/plan-lanes.json").read_text(encoding="utf-8"))
    Path(sys.argv[1]).write_text(file_config(lanes).model_dump_json(), encoding="utf-8")
