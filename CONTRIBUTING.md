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
quality checks (including Markdown links) and distribution build/metadata checks,
while skipping the six-platform pytest matrix and minimum-pytest lane. Within an
admitted lane, the repository's public file-selection action selects affected
test files once; the platform matrix and minimum-pytest job execute that same
plan. CI-esta receives both lane and file explanations, learns JUnit timings,
and validates the aggregate gate. Source and test edits follow dependencies;
scripts, dependency/pytest policy and execution workflow changes retain full
validation. Main, manual/called runs and the `test:full` label run it in full; a
failed planner also runs all tests. Installed-distribution smoke checks use the
same runtime-input decision; README-only changes skip those checks while still
verifying the README embedded in both release archives. Repository routing
controls exercise the committed config against real Git trees, including full and missing-history
controls. Add new non-import execution inputs to `.github/test-lanes.json`.

File planning derives its graph from that same lane config and merges its declared
global execution inputs with the graph's environment inputs. Declare subprocess
and non-import dependencies at their readers. Full plans collect whole-suite
coverage; scoped plans produce JUnit timing evidence without presenting partial
coverage as a whole-suite result. The small execution wrapper only consumes the
public action's JSON file list: it does not implement another selector.
The outer pytest process disables the selective plugin to avoid a second planner
and a hidden dependency of every test on plugin startup. Plugin integration tests
still load it normally in subprocesses and declare that dependency explicitly.
Missing or failed planning runs complete roots, and an empty successful plan never starts
pytest. The aggregate gate still fails when planning fails.

## Conventional Commits

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
for commits you create and PR titles (the squash commit that lands on `main`):

```text
fix(parser): handle empty input
feat: add a new output format
feat(api)!: remove the deprecated argument
docs: clarify installation
```

Allowed types are `feat`, `fix`, `perf`, `revert`, `docs`, `style`,
`refactor`, `test`, `build`, `ci`, and `chore`. Scope is optional.
Use `!` before the colon for breaking changes and explain the migration in the
PR body. Choose the type for the actual change, since release tooling uses it.

The `conventional-commit` check uses
[amannn/action-semantic-pull-request](https://github.com/amannn/action-semantic-pull-request).
It reads PR metadata, including for forks, without checking out contributor code.
If it fails on a title, rename the PR; the edited event reruns the check.
Keep the existing PR and commits. Work-in-progress commits need not be rewritten.

Use **Squash and merge**, with the PR title as the commit title. Check the final
message before merging, including single-commit PRs, and preserve any
`BREAKING CHANGE:` explanation in the body. The repository's squash defaults
support this, but a maintainer can still edit the final message.
Release Please turns these commits into a release PR containing the version,
changelog, and lockfile update. Merging that PR authorizes PyPI publication after
CI. See [RELEASING.md](RELEASING.md) for the version rules and publishing.

## Shared instructions for Codex and Claude

[AGENTS.md](AGENTS.md) is the canonical repository guidance. Codex reads it
directly; Claude reads the tracked `CLAUDE.md -> AGENTS.md` symlink. Edit
`AGENTS.md` once, including commit-policy changes, so both tools receive the
same instructions.

[dallay/agentsync](https://github.com/dallay/agentsync) manages that link through
[agentsync.toml](agentsync.toml). After cloning, or to repair a
missing or stale link, run these commands from the repository root with Node.js
18+ and npm installed:

```bash
npx --yes @dallay/agentsync@1.52.3 apply
npx --yes @dallay/agentsync@1.52.3 status
```

The CLI version is pinned for reproducible setup. Review and update both commands
when upgrading AgentSync. The configuration disables managed gitignore changes
because we intentionally commit the relative link, following AgentSync's
[committed-destination workflow](https://dallay.github.io/agentsync/guides/gitignore-team-workflows/).
Ordinary instruction edits propagate immediately through the link.

On native Windows, enable Developer Mode and Git symlink support
(`git config core.symlinks true`), then run `apply` to repair a checkout that
materialized the link as plain text. Alternatively, use WSL for a checkout in
the Linux filesystem. See the
[Windows setup guide](https://dallay.github.io/agentsync/guides/windows-symlink-setup/).
If AgentSync backs up an existing `CLAUDE.md`, review and preserve any unique
guidance in `AGENTS.md`; do not commit the backup as another instruction source.

## Documentation-only CI

Documentation-only PRs execute zero tests unless a test or lane explicitly
declares that documentation as an input. This includes CI contract tests,
installed-wheel smoke and public-action smoke. Metadata/link/build checks may
still validate documentation without running runtime tests. Declare execution
workflows, selector configuration, helpers, locks and non-import inputs; missing
history or failed planning must execute the full affected lanes and fail the
required planning gate. Main/manual/full checkpoints remain complete runs.
