"""Derive file selection from the same graph and execution inputs as lane admission."""

import sys
from pathlib import Path

from pytest_selective.ci import LaneConfig

file_config = LaneConfig.file_config


if __name__ == "__main__":
    lanes = LaneConfig.model_validate_json(Path(".github/test-lanes.json").read_text(encoding="utf-8"))
    Path(sys.argv[1]).write_text(file_config(lanes).model_dump_json(), encoding="utf-8")
