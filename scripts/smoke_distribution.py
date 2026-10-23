"""Install each built distribution outside the checkout and run the public tutorial."""

import os
import subprocess
import tempfile
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    distributions = sorted((ROOT / "dist").glob("*.whl")) + sorted((ROOT / "dist").glob("*.tar.gz"))
    if len(distributions) != 2:
        raise SystemExit("Expected exactly one wheel and one sdist in dist/")
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    for distribution, version in product(distributions, ("3.11", "3.14")):
        with tempfile.TemporaryDirectory(prefix="selective-install-") as temporary:
            folder = Path(temporary)
            venv = folder / "venv"
            subprocess.run(["uv", "venv", "--python", version, str(venv)], check=True, env=environment)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            cli = venv / ("Scripts/pytest-selective.exe" if os.name == "nt" else "bin/pytest-selective")
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), str(distribution)], check=True, env=environment
            )
            subprocess.run([str(cli), "--help"], cwd=folder, check=True, env=environment, stdout=subprocess.DEVNULL)
            expansion = venv / (
                "Scripts/pytest-selective-expansion.exe" if os.name == "nt" else "bin/pytest-selective-expansion"
            )
            subprocess.run(
                [str(expansion), "--help"], cwd=folder, check=True, env=environment, stdout=subprocess.DEVNULL
            )
            subprocess.run(
                [
                    str(python),
                    "-I",
                    "-c",
                    "from importlib.resources import files; "
                    "assert files('pytest_selective').joinpath('py.typed').is_file(); "
                    "from importlib.metadata import entry_points; "
                    "assert any(e.value == 'pytest_selective.plugin' for e in entry_points(group='pytest11'))",
                ],
                cwd=folder,
                check=True,
                env=environment,
            )
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), f"{distribution}[audit]"], check=True, env=environment
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
