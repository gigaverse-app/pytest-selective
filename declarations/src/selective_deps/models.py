"""Language-independent declaration contracts, with no test-runner imports."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTENTS_PREFIX = "@contents:"


def contents_node(path: str) -> str:
    """A file read as bytes; do not follow its import dependencies."""
    return CONTENTS_PREFIX + path


def file_of(node: str) -> str:
    """The repository-relative path represented by an import or content node."""
    return node.removeprefix(CONTENTS_PREFIX)


class DependencyInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[str]
    reason: str = ""
    kind: Literal["content", "import"] = "import"


class ManifestDependencyRule(DependencyInputs):
    readers: list[str] | None = Field(default=None, min_length=1)
    relative_to: Literal["manifest", "reader"] = "manifest"

    @model_validator(mode="after")
    def _reviewed_without_inputs(self) -> "ManifestDependencyRule":
        if not self.inputs and not self.reason.strip():
            raise ValueError("a rule with no inputs records a reviewed reader and requires a reason")
        return self


class DependencyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dependencies: list[ManifestDependencyRule]
