"""Default environment inputs shared by file selection and whole-lane routing."""

# Match at the repository root and in nested projects with fnmatch's path rules.
# Consumers can replace the list when they own a narrower environment contract.
_ENVIRONMENT_FILES = (
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "pdm.lock",
    "pixi.lock",
    "Pipfile",
    "Pipfile.lock",
    "*requirements*.txt",
    "*requirements*.in",
    "requirements*.lock",
    "pylock*.toml",
    "requirements/**",
    "*constraints*.txt",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    ".pytest.ini",
    "pytest.toml",
    ".pytest.toml",
)
DEFAULT_GLOBAL_INPUTS = tuple(pattern for name in _ENVIRONMENT_FILES for pattern in (name, f"**/{name}"))
