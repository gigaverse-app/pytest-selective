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

### The selection contract

[contracts/selection](contracts/selection/README.md) states the planner's core
promise as a [Quint](https://quint.sh) model and checks it with
[pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect):
generated histories of real commits, each selected by `affected()` and compared
with the model. It runs as its own CI lane, outside the xdist suite, and needs
Node.js 22+ for Quint:

```bash
uv run --group quint pytest -c contracts/selection/quint.ini contracts/selection --quint-require-complete
```

When selection semantics change on purpose, change `selection.qnt` with them and
regenerate the driver (`pytest-quint-connect codegen contracts/selection/quint-connect.json`).
Never drop a witness, mutant or observed field to make it pass.

CI reports each run in one pull-request comment and checks the README's contract block
against it. After a change to the contract's cases, refresh the block from a complete
local run and commit it:

```bash
uv run --group quint pytest-quint-connect report '**/.artifacts/quint-connect/results.json' --readme README.md
```

### Shared implementation owners

| Contract | Owner |
| --- | --- |
| Repository-scoped Git, hook environment isolation, binary and UTF-8 output | `git_operations.py` |
| Private working-tree snapshots, staged inputs and index timestamp preservation | `working_tree.py` |
| Python module names, Unicode matching and dotted import relationships | `ast_imports.py` |
| Test-file discovery and cache exclusions | `test_inventory.py` |
| Repository-relative path containment, including the dot root | `impact_graph.within` |

The expansion guard imports the first three owners directly when run as a script;
keep them stdlib-only. Its snapshot updates Python paths and preserves the stat
cache; the planner rebuilds the staged entries to see edits hidden by index flags
and updates all inputs. Preserve the copied index timestamp: Git uses it to detect
same-size edits made within its stat-cache window. The snapshot tests cover ordinary indexes,
split indexes and linked worktrees without modifying the user's index or HEAD.

## CI and dependency maintenance

CI tests Python 3.11 and 3.14 on Linux, Windows, and macOS. A separate job checks
pytest 8.0.0 on Python 3.11, the plugin's lower bound. It also checks hooks, builds both distribution
formats, validates PyPI metadata, and installs each distribution in an isolated
environment on both Python versions. JUnit retains results and timings on every platform and Python version.
Full runs collect coverage on Python 3.14 on all three operating systems; Python 3.11 runs the same compatibility
tests without a duplicate instrumentation pass. Each runner uses four work-stealing workers.

Use `uv lock --upgrade-package NAME` for a targeted dependency update and run the
affected checks. Dependabot proposes weekly uv and GitHub Actions updates.
Established Actions use published major-version tags; use a published release tag when no major tag exists.
Review release notes when upgrading a major version.

## Pull requests

Explain the user-visible problem and the resulting behavior. Include the exact
validation commands, measured evidence where applicable, and any remaining
limitations. The pull request template provides a short checklist. See
[RELEASING.md](RELEASING.md) for package publication.


## CI lane selection

This repository uses its own `plan-lanes` action. Documentation-only PRs keep
quality checks (including Markdown links) and the documentation build, while
skipping every test lane and the distribution build. A README or LICENSE change
also runs the `package` lane, because both distributions embed them. Within an
admitted lane, the repository's public file-selection action selects affected
test files once; the platform matrix and minimum-pytest job execute that same
plan. CI-esta receives both lane and file explanations, learns JUnit timings,
and validates the aggregate gate. Source and test edits follow dependencies;
scripts, dependency/pytest policy and execution workflow changes retain full
validation. Manual/called/release runs and the `test:full` label run it in full; a
failed planner also runs all tests. Installed-distribution smoke checks use the
same runtime-input decision; README-only changes skip those checks while still
verifying the README embedded in both release archives. Repository routing
controls exercise the committed config against real Git trees, including full and missing-history
controls. Add new non-import execution inputs to `.github/test-lanes.json`.

File planning derives its graph from that same lane config and merges its declared
global execution inputs with the graph's environment inputs. Declare subprocess
and non-import dependencies at their readers. Full plans collect whole-suite
coverage; scoped plans produce JUnit timing evidence without presenting partial
coverage as a whole-suite result. The public [shared-plan executor](docs/shared-plan-execution.md)
consumes the action's JSON file list without implementing another selector.
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
required planning gate. Ordinary PRs and pushes use selection; manual/release/scheduled/full overrides
remain complete checkpoints.

The **Weekly full checkpoint** workflow dispatches CI and public-action smoke
every Monday using [CI-esta's shared action](https://github.com/gigaverse-app/ci-esta/blob/main/docs/weekly-checkpoints.md).
Its small wrapper is generated by `ci-esta checkpoint init`; the source guide
documents schedule, workflow, ref and input overrides. Ordinary runs keep
the shared affected-file plan across all six OS/Python combinations and minimum
pytest. `tests/test_tutorial.py` owns the end-to-end tutorial execution and follows
that plan; there is no second tutorial invocation in each matrix job. JUnit retains
its test result and timing, and full plans also upload whole-suite coverage.

To run both complete checkpoints after a CI change, select **Weekly full checkpoint**
in GitHub Actions and choose **Run workflow**, then inspect the dispatched CI and
public-action results. A green dispatcher means both requests were accepted.
You can also dispatch either target directly. Retrying an ordinary PR run preserves its selection;
use the manual checkpoint when you need full-suite coverage evidence.

## Duplication

`uv run pre-commit install` installs both the staged dry-lint check and the
`prepare-commit-msg` trailer hook, alongside Ruff and documentation checks.
Put your own `ANTHROPIC_API_KEY` in the shell or the ignored `.env`. The hook uses
Sonnet, Python 3.13 and the same accepted baseline as CI. Missing judge credentials
fail strict checking. The trailer records duplicates fixed before the first push,
so the PR sticky includes that local prevention credit.

The required judged `dry-lint` check rejects new blocking duplicates, incomplete
judgments and baseline widening. Forks detect candidates without secrets; the
trusted judge workflow assesses their artifacts. CI's general quality job skips
only the semantic hook, because the dedicated required job owns judging and its
credentials. Other pre-commit hooks still run there.

When a finding appears, inspect both functions. Reuse the existing owner when they
implement one concept, preserve selection/fallback behavior and run the affected
tests. For genuinely distinct concepts, add a narrow `distinct-from` comment and
its reason. Do not weaken thresholds or use blanket ignores to make CI pass.

The PR sticky tracks findings and fixes across pushes. Every default-branch push
can finish folding merged PRs into the repository ledger. The README sign shows
new duplicates prevented separately from old debt cleaned and remaining. Counts
are pairs, not lines or estimated time savings; dismissals never count as cleanup.
The cache-backed ledger starts a new accounting period if evicted.

The weekly/manual **dry-lint audit** retains its reports, then opens or updates one
`dry-lint/ratchet` PR with only the baseline, progress JSON and README metadata.
The inherited `GV_CI_CROSS_REPO_TOKEN` lets that PR run ordinary CI. New debt,
incomplete judging or missing authentication fails visibly. Humans and agents
choose refactors; the audit never edits application code or merges its own PR.

```bash
uv tool install --no-config --python 3.13 'dry-lint[anthropic] @ git+https://github.com/gigaverse-app/dry-lint@v1'
dry-lint sweep --budget-usd 5 --report audit.json --output audit.md
# Review both sides, refactor and test before recording progress.
dry-lint sweep --update --budget-usd 5 --readme README.md --repository gigaverse-app/pytest-selective --repository-id 1430133155
```

Commit the generated metadata with a cleanup, or dispatch the audit after the
cleanup merges. A manual run of the **dry-lint** workflow also calls the same
reusable audit, allowing validation on an adoption branch before the new scheduled
workflow exists on `main`. Ratchet PRs target the selected branch. Preserve the nine-pair adoption history; never delete and
reinitialize the baseline. No-change audits produce no metadata diff. Keep raw
reports and verdict caches outside Git. The scope uses dry-lint's default
exclusions; changes to detection policy require an explicitly reviewed migration.

See the [full adoption playbook](https://github.com/gigaverse-app/dry-lint/blob/main/docs/adoption-playbook.md)
and [sweep semantics](https://github.com/gigaverse-app/dry-lint/blob/main/docs/sweeps.md).
