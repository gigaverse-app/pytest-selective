"""Clean installed-distribution environments shared by both package smoke tests."""

import os
import subprocess
import tempfile
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def installed_distributions(package: str, *, find_links: bool = False):
    distributions = sorted((ROOT / "dist").glob(f"{package}-*.whl")) + sorted(
        (ROOT / "dist").glob(f"{package}-*.tar.gz")
    )
    if len(distributions) != 2:
        raise SystemExit(f"Expected one {package} wheel and sdist")
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    for distribution, version in product(distributions, ("3.11", "3.14")):
        with tempfile.TemporaryDirectory(prefix=f"{package}-install-") as temporary:
            folder = Path(temporary)
            venv = folder / "venv"
            subprocess.run(["uv", "venv", "--python", version, str(venv)], check=True, env=environment)
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            links = ["--find-links", str(ROOT / "dist")] if find_links else []
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), *links, str(distribution)],
                check=True,
                env=environment,
            )
            yield distribution, version, folder, venv, python, environment
