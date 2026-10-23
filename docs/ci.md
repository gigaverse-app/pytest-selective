# Use pytest-selective in CI

Plan on committed revisions with complete Git history and a known passing base.
Keep a scheduled full-suite run. Do not drop unresolved failures merely by moving
the base forward after a failed run.

## GitHub Actions

This job uses the repository's composite action and runs the plan on the checked-out
head. Replace `REVIEWED_COMMIT_SHA` with a reviewed commit of pytest-selective and
adapt dependency installation to your project. The example assumes a uv project
and test paths without spaces (the action's `test_roots` output is space-separated).

```yaml
name: Affected tests
on: [pull_request]
permissions:
  contents: read
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v10
      - id: impact
        uses: gigaverse-app/pytest-selective@main
        with:
          config: .github/test-impact.json
          base: ${{ github.event.pull_request.base.sha }}
          full-roots: tests
      - if: steps.impact.outputs.mode != 'none'
        run: uv sync --locked
      - if: steps.impact.outputs.mode != 'none'
        env:
          TEST_ROOTS: ${{ steps.impact.outputs.test_roots }}
        shell: bash
        run: |
          read -r -a roots <<< "$TEST_ROOTS"
          if [ "${#roots[@]}" -eq 0 ]; then
            echo "Expected test roots for a nonempty plan" >&2
            exit 1
          fi
          uv run --locked pytest "${roots[@]}"
```

The action creates its own Python 3.14 planner environment. Your uv project
controls the test interpreter. `full-roots` must contain the complete roots, not
the previous selection. With `full: 'true'`, the action requests a complete run.

| Planner outcome | Action behavior |
| --- | --- |
| `scoped` | Run selected files |
| `full` | Run complete configured roots |
| `none` | Skip pytest |
| Operational failure, such as missing Git history | Run `full-roots` |
| Invalid dependency declaration / unparseable Python | Fail with a diagnostic; fix the input |

Read the [action inputs](../test-impact/action.yml) for cache
warming, shard planning, explanations, and optional first-party dependency pins.
Advanced base reuse requires proof that the reused revision passed the applicable
checks. Start with the PR base and full history.

## Consume JSON in another runner

Run `pytest-selective affected ... --output selection.json` and inspect its exit
status before consuming the file. A nonzero exit must never reuse a stale report.
On exit 1, run your complete test roots; on exit 2, repair the declaration error.
After a successful plan, use an argument list:

```python
import json
import subprocess
import sys
from pathlib import Path

report = json.loads(Path("selection.json").read_text())
if report["mode"] == "full":
    roots = ["tests"]  # Your complete test roots.
else:
    roots = report["selected"]
if roots:
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *roots]))
print("No affected test files; pytest skipped")
```

The JSON form preserves paths containing spaces. Do not use shell evaluation to
execute report contents. Preserve your test-lane filters and conformance policy;
file selection does not override those requirements.

## Select whole CI lanes

For tests that must produce complete conformance evidence, use
[`plan-lanes`](../plan-lanes/action.yml) or
`python -m pytest_selective.ci` with a config:

```json
{
  "graph": {"module_roots": ["src", "."], "test_roots": ["tests"]},
  "lanes": {
    "unit": {"roots": ["tests/unit"]},
    "live": {"roots": ["tests/live"], "inputs": ["external-contracts/**"]}
  }
}
```

An affected test selects its entire lane. Explicit lane inputs cover external
checkouts, generated tests, and subprocess dependencies that imports cannot see.
CI/dependency metadata changes and operational planning failures run every lane.
Review collection policy and set `graph.pytest_policy` from the `fingerprints`
command before expecting narrowing in a configured pytest project.

### Depend on one workflow job

A lane that depends on the workflow file which runs it would otherwise run for
every edit to that file, including a version bump of the planning action itself.
Name the job instead: `<workflow path>#<job id>`.

```json
{
  "lanes": {
    "unit": {"roots": ["tests/unit"], "inputs": [".github/workflows/ci.yml#tests"]}
  },
  "global_inputs": ["uv.lock", "pyproject.toml", ".github/actions/**"]
}
```

The lane runs when the parsed YAML of that job differs between base and head,
or when anything outside `jobs:` does (triggers, `env`, `defaults`,
`permissions`, `concurrency`), because every job inherits those. Comments and
formatting do not count. Adding, removing or renaming the job, or deleting the
file, selects the lane. Other jobs are not followed through `needs`: list each
job whose change can alter the lane's result, such as one that builds an
artifact the tests download. Reusable workflows and local actions are separate
files; list them as ordinary inputs.

A skipped lane whose workflow file changed elsewhere reports
`unchanged job: <path>#<job>`. A job id that the workflow does not define is a
declaration error (exit 2) on every plan, and a workflow that does not parse
runs every lane. The workflow path must not match
`global_inputs`, which runs every lane first; the default `.github/**` does, so
a config with a job input must set `global_inputs` explicitly.

The action returns a `lanes` JSON object. Expose it as a planning-job output,
then gate each expensive job with `always() && !cancelled()` and either a true
lane value **or a failed planning job**. This preserves tests if planning fails.
Run the action with `full: true` on main, schedules, and full-test overrides.
Selected jobs retain all of their existing tests and evidence checks.


The JSON report also includes `lane_reasons`, naming affected test files, changed
root files, explicit inputs, global inputs and fallback causes. Skipped lanes say
`no affected tests or changed inputs`. GitHub's step summary displays this report.
If an affected or deleted test has no configured lane root, the planner runs all
configured lanes and names the unmapped test. Map new test directories to a job
that actually executes them; fallback cannot create a missing execution job.

The action also uploads the report as the `test-lane-selection` artifact; set
`artifact-name` to rename it, or to an empty string to skip the upload.
[CI-esta](https://github.com/gigaverse-app/ci-esta)'s report renders it as the
pull-request sticky's lane section: which lanes ran and why, and the runner time
the skipped jobs took on the default branch's last full run. See
[how the two fit together in a Python project](https://github.com/gigaverse-app/ci-esta/blob/main/docs/integrations.md#getting-the-most-from-both-in-a-python-project).
