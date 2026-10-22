# Changelog

## Unreleased

- Guard hidden, TOML, nested and explicitly declared pytest configuration against unsafe empty selection; retain full-suite dependency updates for configured plugins.

- Lane inputs can name one workflow job (`.github/workflows/ci.yml#tests`), so edits to other jobs, such as a planner pin bump, no longer run the lane.
- Batch first-party commit probes and avoid redundant Git maintenance in bounded dependency caches.
- Isolate nested audit-test temporary directories to avoid unrelated fixture cleanup.
- Add matched Windows full-suite timing, test inventory and coverage evidence.
- `plan-lanes` uploads its plan as the `test-lane-selection` artifact, which CI-esta renders as the sticky's lane section.

- Guided README, configuration reference, CI integration, and runnable regression tutorial.
- Coverage artifacts, Linux/Windows/macOS CI, minimum-pytest checks, and isolated wheel/sdist smoke tests.
- Locked Ruff pre-commit hooks, local documentation link checks, and dependency updates.
- Version-checked PyPI trusted-publishing workflow and maintainer release guide.

## 0.1.0a1 — initial source extraction

Initial alpha source version; this heading does not imply a PyPI release.

- Git-based Python test selection using both base and head dependency graphs.
- Reader-owned dependency declarations, runtime audits, and selection explanations.
- Cached graph planning and duration-based shard sizing.
- Standalone CLI and GitHub Actions integration.

See [PROVENANCE.md](PROVENANCE.md) for the extraction boundary.
