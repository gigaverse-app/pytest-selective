# Contributing to pytest-selective

Use Python 3.11+, Git 2.24+, and uv. The planner operates on immutable Git trees;
tests should exercise real temporary repositories through the existing helpers
in `tests/testing/git_repo.py`.

```bash
uv sync --locked
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q --cov --cov-report=term-missing
uv run python scripts/tutorial.py
uv build
uv run twine check --strict dist/*
uv run python scripts/smoke_distribution.py
```

Ruff lint and formatting use the versions in `uv.lock`, both locally and in CI.
Hooks fix repairable lint and formatting issues; review and stage their edits.
The Markdown hook checks local file links. It does not check external URLs or
heading anchors. Tests run separately so normal commits stay quick.

## Preserve selection safety

For a bug, first add a failing regression using an actual Git change. Assert the
selected paths and observable outcome. Include base and head behavior, invalid
inputs, and fallback handling when relevant. Prefer existing helpers over mocks
of Git or the selector. Do not weaken selection or add broad ignores to hide a
failure. Keep root conftests small: every importer inherits their dependencies.

Changes to collection policy, runtime auditing, or the composite action need tests
at that boundary. Update the tutorial when the public command contract changes.
Keep performance claims tied to reproducible measurements and their limitations.

## CI and dependency maintenance

CI tests Python 3.11 and 3.14 on Linux, Windows, and macOS. A separate job checks
pytest 8.0.0 on Python 3.11, the plugin's lower bound. It also checks hooks, builds both distribution
formats, validates PyPI metadata, and installs each distribution in an isolated
environment on both Python versions. Evidence artifacts carry coverage and tutorial output on every platform and Python version.

Use `uv lock --upgrade-package NAME` for a targeted dependency update and run the
affected checks. Dependabot proposes weekly uv and GitHub Actions updates.
Actions are pinned to commits. Review their release notes before updating pins.

## Pull requests

Explain the user-visible problem and the resulting behavior. Include the exact
validation commands, measured evidence where applicable, and any remaining
limitations. The pull request template provides a short checklist. See
[RELEASING.md](RELEASING.md) for package publication.


## CI lane selection

This repository uses its own `plan-lanes` action. Documentation-only PRs keep
quality checks (including Markdown links) and distribution build/install checks,
while skipping the six-platform pytest matrix and minimum-pytest lane. Source,
tests, scripts, dependency/pytest policy and workflow changes run the complete
matrix. Main, manual/called runs and the `test:full` label run it in full; a
failed planner also runs all tests. Repository routing controls exercise the
committed config against real Git trees, including full and missing-history
controls. Add new non-import execution inputs to `.github/test-lanes.json`.
