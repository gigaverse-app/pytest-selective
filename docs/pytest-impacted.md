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
