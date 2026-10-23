# Run affected tests before committing

## Native pytest plugin

Installing pytest-selective registers its `pytest11` entry point. Plain `pytest`
is unchanged; opt in with `pytest --selective`. Pytest is now a runtime dependency;
the existing `[audit]` extra remains accepted for compatibility.

```bash
uv add --dev pytest-selective
uv run pytest --selective
uv run pytest --selective tests/test_checkout.py -k discount
uv run pytest --selective --selective-base origin/main -n auto
uv run pytest --no-selective
```

Without an impact config, the plugin discovers Python test files throughout the
Git repository using pytest's `python_files` patterns, with `src` and the repository
root as module roots. Pytest still controls which directories and items to collect.
Use your existing `ImpactConfig` JSON to retain reviewed dependencies, globals,
test roots, collection fingerprints and other project-specific rules:

```bash
pytest --selective --selective-config .github/test-impact.json
```

Options can also live in `pytest.ini` or `[tool.pytest.ini_options]`:

```ini
[pytest]
selective = true
selective_config = .github/test-impact.json
selective_base = HEAD
```

The config path is relative to pytest's rootdir; paths inside it remain relative
to the Git root. CLI values override ini values. `--no-selective` overrides both
`--selective` and the ini default. `-p no:selective` prevents plugin loading.
With `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, explicitly load it using
`-p pytest_selective.plugin`.

The base defaults to HEAD. A supplied ref is compared directly, not via an
implicit merge-base, and the head is always the working tree being tested.
Both committed branch changes and local edits therefore count. xdist receives
one controller-generated plan; workers do not repeat snapshotting or planning.

Native mode collects normally, then deselects unaffected known Python tests.
Doctests, custom item types and files outside the graph remain runnable. This
preserves collection errors and pytest's path, node-ID, `-k` and `-m` behavior,
but it does not save collection/import time. Use the pre-collection runner below
when avoiding those imports matters. Unknown dynamic runtime dependencies still
need declarations; file selection is not proof of whole-suite coverage.

The terminal summary reports the plan and fallback reasons. A selection that
deselects every remaining test exits successfully. An empty suite or a `-k`/`-m`
filter matching nothing retains pytest's exit code 5. Errors and failed tests
remain failures. Missing Git/history/cache access falls back to the complete
requested suite; invalid JSON and dependency declarations are usage errors.
Without JSON, the current pytest policy is fingerprinted in memory and a base
policy mismatch runs full. Explicit JSON retains its reviewed fingerprints.

This interface learns from [pytest-impacted's opt-in pytest integration](https://github.com/promptromp/pytest-impacted).
Its implementation uses pytest-selective's existing snapshots, graph and selection
rules, shared with the CLI and CI actions.

## Pre-collection runner

For an ordinary pytest suite with a reviewed impact configuration:

```bash
pytest-selective run --config .github/test-impact.json -- -q
```

This compares HEAD with staged, unstaged and nonignored untracked files, then
starts pytest with only the selected paths. A successful empty selection exits
without starting pytest. Missing Git history or a cache failure runs the complete
configured test roots. Invalid declarations remain errors that must be corrected.
Use `--full` for a checkpoint or a whole-suite coverage requirement.

```bash
pytest-selective run --config .github/test-impact.json --base origin/main -- -x
pytest-selective run --config .github/test-impact.json --full -- -q
pytest-selective affected --config .github/test-impact.json --working-tree --output plan.json
```

`--base` names the exact comparison revision; use a merge-base explicitly when
that is the change set you intend. Without `--working-tree`, the existing planner
still reads committed trees and defaults to `HEAD^..HEAD`.

The local snapshot uses a temporary private Git index. It does not change your
staging area, branch, HEAD or working files, and creates no commit. It writes
unreachable Git tree/blob objects that normal Git garbage collection can reclaim.
The runner keeps its graph cache inside Git's private directory, including linked
worktrees. Planning and execution assume files are not concurrently being edited.

Pass pytest options after `--`; exit status comes from pytest. Nonstandard
collectors, doctests and whole-suite coverage need a full run with their usual
arguments. CI lanes that require complete evidence should continue using
`plan-lanes`, which can avoid service startup as well as test execution.

Full plans invoke the configured roots. If a scoped file list exceeds the
operating system's command-line limit, the runner reports the fallback and
retries those complete roots once. Other process-start failures remain errors.

## Environment inputs

`ImpactConfig.global_inputs` now defaults to common Python environment and pytest
configuration files: uv/Poetry/PDM/Pipenv/Pixi/PEP 751 locks, requirements and
constraints files, packaging files, and pytest configuration. A matching change
selects every test even without an import edge. A proven first-party pin change
can still narrow its declared lock/manifest inputs.

Consumers with an explicitly reviewed narrower contract can replace
`global_inputs`, including with `[]`. Keep non-import runtime inputs declared.
`LaneConfig.global_inputs` is the additional whole-lane policy; replacing it does
not remove the graph's default environment protection.
