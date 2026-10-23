# Changelog

## Unreleased

- Register a native pytest plugin: `pytest --selective`, ini defaults, optional existing impact JSON, an exact comparison base, and `--no-selective` for full execution.
- Reuse the existing working-tree snapshots and dependency planner; share one plan with xdist workers and preserve unknown collectors, doctests, normal pytest filtering and failure statuses.
- Install pytest as a runtime dependency; retain the audit extra and all CLI/CI interfaces.

## 0.1.0 (2026-10-23)

First PyPI release.

- Run affected local edits before committing with `run` and `affected --working-tree`, preserving the user's Git index and HEAD.
- Share conservative environment-file invalidation between file selection and CI lanes, covering other Python installers as well as uv.
- Reuse one AST traversal and skip unnecessary comment tokenization; real-backend parser records are unchanged with a measured 52.1% median parsing-time reduction.
- Keep source analysis independent of warning-as-error settings through a shared parser used by import guards and CI-esta.
- Preserve explicit global-input precedence over name narrowing, and retry oversized local pytest commands once with complete roots.

- Guard hidden, TOML, nested and explicitly declared pytest configuration against unsafe empty selection; retain full-suite dependency updates for configured plugins.
- Reuse Git tree listings within a process and start fewer Git processes in test fixtures; Windows CI measures coverage on Python 3.14 only.

- Lane inputs can name one workflow job (`.github/workflows/ci.yml#tests`), so edits to other jobs, such as a planner pin bump, no longer run the lane.
- Batch first-party commit probes and avoid redundant Git maintenance in bounded dependency caches.
- Isolate nested audit-test temporary directories to avoid unrelated fixture cleanup.
- Add matched Windows full-suite timing, test inventory and coverage evidence.
- `plan-lanes` uploads its plan as the `test-lane-selection` artifact, which CI-esta renders as the sticky's lane section.

- Guided README, configuration reference, CI integration, and runnable regression tutorial.
- Coverage artifacts, Linux/Windows/macOS CI, minimum-pytest checks, and isolated wheel/sdist smoke tests.
- Locked Ruff pre-commit hooks, local documentation link checks, and dependency updates.
- Version-checked PyPI trusted-publishing workflow and maintainer release guide.

### Initial source extraction

- Git-based Python test selection using both base and head dependency graphs.
- Reader-owned dependency declarations, runtime audits, and selection explanations.
- Cached graph planning and duration-based shard sizing.
- Standalone CLI and GitHub Actions integration.

See [PROVENANCE.md](PROVENANCE.md) for the extraction boundary.
