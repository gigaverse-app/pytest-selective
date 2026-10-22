# Lessons from pytest-impacted

Reviewed the upstream [usage guide](https://github.com/promptromp/pytest-impacted/blob/main/docs/usage.md)
and [project overview](https://github.com/promptromp/pytest-impacted) on 2026-10-22,
after publishing the initial extraction and preparing Due and pytest-obligation adoption.
This is a design comparison; no upstream implementation was copied.

## Applied

- **Python 3.11+ portability.** The planner need not force the application's
  interpreter version. Removed incidental 3.14-only syntax and APIs. The narrow
  dependency-glob language is tested against the original Python 3.14 glob
  implementation; interpreter-specific caches remain separate. Parse source with
  a Python version that understands its syntax; the CI action still uses 3.14.
- **Explicit Git arguments.** Revision resolution now uses `--end-of-options`,
  the boundary described by pytest-impacted. Option-shaped references fail safely.
  A real two-repository regression additionally showed that inherited Git hook
  variables could redirect analysis despite `git -C`; graph reads now clear
  those location overrides. The regression failed before the fix.

- **Visible selection gaps.** Upstream warns when changed Python files reach no
  tests. The CI lane adapter has an additional mapping boundary: a selected (or
  deleted) test may have no configured lane root. A real Git regression reproduced
  that case incorrectly skipping every job. It now falls back to all configured
  lanes and names the unmapped tests. Maintainers must still map the new directory
  to a job that actually executes it; running existing lanes cannot invent that job.
- **Explain each job decision.** Lane JSON now includes `lane_reasons`: affected
  tests, changed root files, explicit inputs, global inputs, or the full-suite
  fallback cause. Skipped lanes explicitly report no affected tests or changed
  inputs. Existing boolean GitHub outputs stay compatible. This turns broad
  invalidators into reviewable evidence when deciding what can safely be narrowed.

## Useful next directions

The upstream plugin makes working-tree changes and pytest-native selection easy
to request. Our current CLI deliberately analyzes committed trees. A working-tree
mode must preserve the user's index and include staged, unstaged, untracked,
renamed, and deleted inputs. A pytest plugin must preserve custom collectors,
inherited tests, and generated conformance evidence; selecting whole CI lanes is
the safe initial integration for the current adopters.

The upstream optional accelerated parser is worth benchmarking only if graph
construction becomes the bottleneck. Our blob and snapshot caches already avoid
repeat parsing; selection counts are not evidence of runtime speedups.

We retain reader-owned dependency declarations, old/new graph union, audit
records, and explanations rather than replacing the proven selector during
extraction. Full-suite checkpoints remain necessary for dynamically loaded code.

Upstream's branch mode uses merge bases, including multiple merge bases for
criss-cross histories. That is useful for a future local branch command; current
CI callers supply explicit comparison commits. A future mode needs real divergent
history tests, not a silent change to the existing two-tree API.

Subprocesses and dynamic framework registration still need explicit inputs.
Upstream's optional handling of application imports through conftest is not a
safe default for our adopters: preserve startup/conftest edges and full generated
conformance lanes. In Due, tracing the widget benchmark's subprocess imports
found a missing shared process helper while proving unrelated example apps need
not trigger the benchmark. Keep full scheduled/main/manual checkpoints and the
`test:full` escape hatch.
