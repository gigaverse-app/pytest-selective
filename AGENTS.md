# Working on pytest-selective

For adopting the tool in another repository, use
[the portable skill](skills/pytest-selective/SKILL.md). This file describes work
on pytest-selective itself.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup and validation. Use the locked
  environment: `uv sync --locked`, `uv run pre-commit run --all-files`,
  `uv run pytest -q -n 4`. For packaging changes also build, run strict Twine,
  `scripts/check_metadata.py` and `scripts/smoke_distribution.py`.
- Reproduce selection bugs using real temporary Git repositories and existing
  `tests/testing/git_repo.py` helpers. Cover base and head trees, deleted inputs,
  explicit declarations and the relevant fallback. Do not mock away selection.
- Planner output is about committed revisions. Preserve full execution on
  operational uncertainty and diagnostics for invalid declarations. An empty
  selection is not an empty pytest argument list.
- Keep consumer routing regressions in the always-running quality job. Update
  `.github/test-lanes.json` when adding execution inputs; preserve full main/manual
  checkpoints and the `test:full` override.
- The README's performance numbers are scenario-specific observations. Keep
  claims linked to [raw evidence](docs/benchmarks/2026-10-22-routing.md); distinguish
  runner-seconds, elapsed time and billing. Skill/example edits need usable links
  and verified commands, not tests that merely assert prose wording.
