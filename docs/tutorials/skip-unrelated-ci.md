---
title: Skip unrelated CI jobs for documentation changes
description: Route complete pytest lanes safely, retain docs and package checks, and measure the difference using real GitHub Actions evidence.
---

# Skip unrelated CI jobs for documentation changes

A README edit should still check your documentation and package description.
It usually does not need to start PostgreSQL, Redis, and every OS test runner.
Use whole-lane selection when a test suite must produce complete conformance
evidence. An affected lane runs all its existing tests and validators.

## What this achieved in a real repository

On 2026-10-22, pytest-selective compared a README-only PR with and without the
`test:full` override at the same head and tested merge revision:

| Metric | Full control | Selected run | Direction |
| --- | ---: | ---: | --- |
| Executed jobs | 10 | 3 | Fewer unrelated runners |
| Sum of runner execution | 627 seconds | 48 seconds | Lower is better |
| Workflow elapsed | 211 seconds | 26 seconds | Lower is better |

The [full run](https://github.com/gigaverse-app/pytest-selective/actions/runs/39849815319)
and [selected run](https://github.com/gigaverse-app/pytest-selective/actions/runs/39849575401)
both used head `4d571a357752030723034eb492c2a88fde7bc686` and merge
`918bed92b3cfecb19f474355da5512b1f894d6a5`. Quality, routing regressions,
documentation links, archive descriptions, and installed-wheel checks remained.
The six platform/Python jobs and minimum-pytest lane were unaffected and skipped.

This one sequential pair used 92.3% fewer runner-seconds. It is not a prediction
for your project or a billing estimate. Cache, queue, runner, and order variation
affect elapsed time. The counts describe the measured workflow before this
documentation site added its own build. [Raw timestamps and method](../benchmarks/2026-10-22-routing.md).

## 1. Identify complete lanes and non-Python inputs

Start with one lane if your tests share a global contract. Create
`.github/test-lanes.json` and adapt the paths to your repository:

```json
{
  "graph": {"module_roots": ["src", "."], "test_roots": ["tests"]},
  "lanes": {
    "tests": {
      "roots": ["tests"],
      "inputs": ["src/**", "tests/**", "conftest.py", "scripts/**"]
    }
  },
  "global_inputs": [
    "pyproject.toml", "uv.lock", ".python-version",
    ".github/test-lanes.json", ".github/workflows/ci.yml", "actions/**"
  ]
}
```

This deliberately treats any source change as affecting the complete test lane.
Add service configuration, generated inputs, fixtures loaded by filename,
subprocess helpers, and external checkout pins. Static imports cannot discover
every runtime dependency. A broad global input takes precedence over narrower
Python analysis; declaring `.github/**` would select tests for PR-template edits.

Configured pytest collection policy also needs review. Follow the
[configuration and fingerprints guide](../configuration.md) before expecting
narrowing in a repository with pytest settings or custom collection hooks.
The [executable selection tutorial](../tutorial.md) gives a small Git repository
you can use to understand the fallback behavior first.

## 2. Plan before starting expensive runners

Add a planning job to your existing workflow:

```yaml
select-tests:
  runs-on: ubuntu-latest
  outputs:
    lanes: ${{ steps.plan.outputs.lanes }}
  steps:
    - uses: actions/checkout@v7
      with:
        fetch-depth: 0
    - id: plan
      uses: gigaverse-app/pytest-selective/actions/plan-lanes@v1
      with:
        config: .github/test-lanes.json
```

Keep the test job's services, matrix, commands, coverage and conformance checks.
Add this dependency and condition:

```yaml
needs: select-tests
if: >-
  ${{ always() && !cancelled() && (needs.select-tests.result != 'success' ||
      fromJSON(needs.select-tests.outputs.lanes).tests) }}
```

The failed-planner branch is necessary: a planning failure must not turn into a
passing empty test run. An invalid declaration should still block the aggregate
gate while you fix it. Keep quality, docs, package builds, and the required gate
outside this condition. Use the [strict gate integration](../ci-toolkit.md) to
accept a skip only when a successful plan explicitly says that lane is unaffected.

## 3. Prove the routing boundaries

Exercise actual Git commits, not a function that classifies extensions:

| Change or condition | Required result |
| --- | --- |
| README prose | Test lane skipped; docs and package checks pass |
| Source, fixture, subprocess helper, or test | Complete affected lane runs |
| Lockfile, collection policy, or execution workflow | Required lanes run |
| Missing history or operational uncertainty | Conservative full execution |
| Invalid configuration | Diagnostic and failed required gate |
| Ordinary PR or main push containing only unreferenced docs | Zero tests |
| Manual/release checkpoint, explicit rerun, or `test:full` | Full execution |

Select these routing tests through declared dependencies on configuration,
execution workflows, helpers and the inputs they inspect. Include wheel smoke,
tutorials and separate action workflows in the same test-admission inventory.
Unreferenced documentation should execute zero tests, including after merge.
Metadata and documentation validators can still run. Retain a scheduled full
checkpoint. Do not advance a known-passing base past unresolved failures.
Use [job-specific workflow inputs](../ci.md#depend-on-one-workflow-job) only when
you can enumerate every job, action, and reusable workflow that affects a lane.

## 4. Measure one equivalent pair

Open a README-only probe PR. Save the source SHA, tested merge, run ID and attempt
of its successful selected run. Add `test:full`, then explicitly rerun the workflow at that revision. A label
change alone may not trigger CI. The example also forces full execution on
reruns. Do not change source or workflow settings between the paired runs. Compare successful completed runs;
keep cancelled experiments and observer overhead separate.

Use [CI-esta's critical-path tutorial](https://ci-esta.readthedocs.io/en/latest/docs/tutorials/measure-critical-path/)
to collect elapsed time, runner-seconds, steps and the real dependency chain.
Repeat the pair before claiming an average improvement. If setup or one test lane
still dominates, optimize its execution while retaining the same checks.
