"""Prove both release archives contain the current package README as their description."""

import email.policy
import tarfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_metadata(raw: bytes, readme: str, project: str = "pytest-selective") -> None:
    metadata = Parser(policy=email.policy.default).parsestr(raw.decode("utf-8"))
    assert metadata["Name"] == project, "wrong distribution name"
    assert metadata["Description-Content-Type"] == "text/markdown", "README must render as Markdown"
    description = metadata.get_payload()
    assert isinstance(description, str), "expected a text description"
    assert description.strip() == readme.strip(), "distribution description differs from README.md"


def main() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    for project, folder in (("pytest-selective", ROOT), ("selective-deps", ROOT / "declarations")):
        assert tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == version
        readme = (folder / "README.md").read_text(encoding="utf-8")
        stem = project.replace("-", "_")
        wheels = list((ROOT / "dist").glob(f"{stem}-*.whl"))
        sdists = list((ROOT / "dist").glob(f"{stem}-*.tar.gz"))
        assert len(wheels) == len(sdists) == 1, f"expected one wheel and one sdist for {project}"
        with zipfile.ZipFile(wheels[0]) as wheel:
            metadata = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
            assert len(metadata) == 1
            check_metadata(wheel.read(metadata[0]), readme, project)
        with tarfile.open(sdists[0]) as sdist:
            metadata = [member for member in sdist if member.name.endswith("/PKG-INFO") and member.name.count("/") == 1]
            assert len(metadata) == 1
            stream = sdist.extractfile(metadata[0])
            assert stream is not None
            check_metadata(stream.read(), readme, project)
        print(f"{project}: wheel and sdist contain the current Markdown README")


if __name__ == "__main__":
    main()
