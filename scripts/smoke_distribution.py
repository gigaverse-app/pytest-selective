"""Install each built distribution outside the checkout and run the public tutorial."""
# The distributions job runs this script, which runs the tutorial by path:
# gv:test-dependency: scripts/tutorial.py

import os
import subprocess
from pathlib import Path

from smoke_environments import installed_distributions

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    from smoke_declarations import smoke as smoke_declarations

    smoke_declarations()
    for distribution, version, folder, venv, python, environment in installed_distributions(
        "pytest_selective", find_links=True
    ):
        cli = venv / ("Scripts/pytest-selective.exe" if os.name == "nt" else "bin/pytest-selective")
        subprocess.run([str(cli), "--help"], cwd=folder, check=True, env=environment, stdout=subprocess.DEVNULL)
        expansion = venv / (
            "Scripts/pytest-selective-expansion.exe" if os.name == "nt" else "bin/pytest-selective-expansion"
        )
        subprocess.run([str(expansion), "--help"], cwd=folder, check=True, env=environment, stdout=subprocess.DEVNULL)
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from importlib.resources import files; "
                "assert files('pytest_selective').joinpath('py.typed').is_file(); "
                "from importlib.metadata import entry_points; "
                "assert any(e.value == 'pytest_selective.plugin' for e in entry_points(group='pytest11')); "
                "from pytest_selective.parse_batch import parse_records; "
                "sources = [b'import application', b'pytest_plugins = [\"support\"]']; "
                "assert parse_records(sources, 2) == parse_records(sources, 1)",
            ],
            cwd=folder,
            check=True,
            env=environment,
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--find-links",
                str(ROOT / "dist"),
                f"{distribution}[audit]",
            ],
            check=True,
            env=environment,
        )
        subprocess.run([str(python), str(ROOT / "scripts/tutorial.py")], cwd=folder, check=True, env=environment)
        # No -p or checkout on PYTHONPATH: wheel/sdist entry-point discovery
        # must work in a separate consumer, including the safe no-Git path.
        consumer = folder / "consumer"
        consumer.mkdir()
        (consumer / "test_installed.py").write_text("def test_installed(): pass\n", encoding="utf-8")
        subprocess.run(
            [str(python), "-I", "-m", "pytest", "--selective", "-q"],
            cwd=consumer,
            check=True,
            env=environment,
        )
        print(
            f"Verified {distribution.name} on Python {version}: CLI, typing marker, pytest plugin, real selection",
            flush=True,
        )


if __name__ == "__main__":
    main()
