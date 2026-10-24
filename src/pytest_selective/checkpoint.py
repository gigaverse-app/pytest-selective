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


def full_checkpoint_reason(value: str) -> str | None:
    """Resolve auto once at planning; uncertain event metadata requires full work.

    Explicit booleans bypass event policy, but never bypass the planners' missing
    history/configuration fallbacks. CLI callers remain selective unless they
    request ``--full`` or ``--full auto``.
    """
    if value == "true":
        return "full suite explicitly requested (--full true)"
    if value == "false":
        return None
    if value != "auto":
        raise argparse.ArgumentTypeError("full must be auto, true, or false")
    try:
        event = os.environ.get("GITHUB_EVENT_NAME", "")
        if event == "push":
            return None
        if event in {"workflow_dispatch", "workflow_call", "schedule", "release"}:
            return f"full suite required by {event} checkpoint"
        if event != "pull_request":
            return "full suite fallback: unsupported or missing event metadata"
        payload = _PullRequestEvent.model_validate_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        return (
            "full suite requested by test:full label"
            if any(label.name == "test:full" for label in payload.pull_request.labels)
            else None
        )
    except (KeyError, OSError, ValueError, ValidationError):
        return "full suite fallback: pull request event metadata unavailable or invalid"


def full_checkpoint(value: str) -> bool:
    """Compatibility boolean API; the planners retain the reason as well."""
    return full_checkpoint_reason(value) is not None
