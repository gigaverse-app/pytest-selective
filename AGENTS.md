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
- The planner's import, conftest, declaration and content-read closure, its parse-error
  stop, its selection against older bases and its graph cache's transparency are also a
  Quint contract in
  `contracts/selection`. After changing selection, run it (CONTRIBUTING.md, *The selection
  contract*); extend the model rather than weakening it when the promise changes.
- Planning supports committed revisions and explicit working-tree snapshots. Preserve full execution on
  operational uncertainty and diagnostics for invalid declarations. An empty
  selection is not an empty pytest argument list.
- Select consumer routing regressions by their declared execution/configuration inputs. Update
  `.github/test-lanes.json` when adding execution inputs; preserve explicit full/manual
  checkpoints and the `test:full` override.
- The README's performance numbers are scenario-specific observations. Keep
  claims linked to [raw evidence](docs/benchmarks/2026-10-22-routing.md); distinguish
  runner-seconds, elapsed time and billing. Skill/example edits need usable links
  and verified commands, not tests that merely assert prose wording.

## Commits and pull requests

- Use Conventional Commits for commits you create and PR titles:
  `type(optional-scope): description`, for example
  `fix(parser): handle empty input`.
- Allowed types: `feat`, `fix`, `perf`, `revert`, `docs`, `style`,
  `refactor`, `test`, `build`, `ci`, and `chore`. Choose the type for the
  actual change. Mark breaking changes with `!` before the colon and explain
  the migration in the PR body.
- Repair an invalid PR title in place. Preserve useful work; do not close or
  replace the PR, or rewrite existing commits just to satisfy the title check.
- Squash merges use the checked PR title. Keep any `BREAKING CHANGE:` details
  in the body. Follow [CONTRIBUTING.md](CONTRIBUTING.md) and
  [RELEASING.md](RELEASING.md).

## Releases

Release Please derives versions and changelogs from Conventional Commits. Let
it prepare the release PR; do not hand-edit versions for ordinary changes.
Merging a release PR authorizes PyPI publication after CI. Follow RELEASING.md.

## Shared agent instructions

Edit this root `AGENTS.md` as the single source for Codex and Claude.
`CLAUDE.md` is an AgentSync-managed relative symlink to this file, not a
separate instruction document. The configuration is
[agentsync.toml](agentsync.toml). To restore and verify the link:

```bash
npx --yes @dallay/agentsync@1.52.3 apply
npx --yes @dallay/agentsync@1.52.3 status
```

Keep the symlink tracked in Git. See CONTRIBUTING.md for platform setup.

## Documentation-only CI

Documentation-only PRs execute zero tests unless a test or lane explicitly
declares that documentation as an input. This includes CI contract tests,
installed-wheel smoke and public-action smoke. Metadata/link/build checks may
still validate documentation without running runtime tests. Declare execution
workflows, selector configuration, helpers, locks and non-import inputs; missing
history or failed planning must execute the full affected lanes and fail the
required planning gate. Ordinary PRs and pushes use selection; manual/release/scheduled/full overrides
remain complete checkpoints.

## GitHub Actions versions

- ALWAYS use published major-version tags for established GitHub Actions, for example `actions/checkout@v7` and `actions/upload-artifact@v7`, so compatible fixes arrive without per-commit maintenance. NEVER replace those tags with commit hashes unless the user explicitly requests that exact exception. If a publisher has no major-version tag, use its published release tag rather than inventing a ref or substituting a hash.
- ALWAYS use `gigaverse-app/dry-lint@main` until its v1 launch, then use `@v1`. Apply the same ref in workflow examples and adoption instructions.
