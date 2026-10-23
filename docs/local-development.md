# Run affected tests before committing

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
