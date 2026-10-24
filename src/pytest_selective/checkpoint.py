"""One full-checkpoint policy shared by file and lane action entrypoints."""

import argparse
import os
from pathlib import Path

from pydantic import BaseModel, ValidationError


class _Label(BaseModel):
    name: str


class _PullRequest(BaseModel):
    labels: list[_Label]


class _PullRequestEvent(BaseModel):
    pull_request: _PullRequest


def full_checkpoint(value: str) -> bool:
    """Resolve auto once at planning; uncertain event metadata requires full work.

    Explicit booleans bypass event policy, but never bypass the planners' missing
    history/configuration fallbacks. CLI callers remain selective unless they
    request ``--full`` or ``--full auto``.
    """
    if value in {"true", "false"}:
        return value == "true"
    if value != "auto":
        raise argparse.ArgumentTypeError("full must be auto, true, or false")
    try:
        if int(os.environ.get("GITHUB_RUN_ATTEMPT", "0")) != 1:
            return True
        event = os.environ.get("GITHUB_EVENT_NAME", "")
        if event == "push":
            return False
        if event != "pull_request":
            return True
        payload = _PullRequestEvent.model_validate_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        return any(label.name == "test:full" for label in payload.pull_request.labels)
    except (KeyError, OSError, ValueError, ValidationError):
        return True
