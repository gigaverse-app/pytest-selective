# Use pytest-selective in CI

Plan on committed revisions with complete Git history and a known passing base.
Keep a scheduled full-suite run. Do not drop unresolved failures merely by moving
the base forward after a failed run.

PR and push reruns preserve the selection policy for the same base, head and
inputs. Rerunning does not request the full suite. Use `full: 'true'`, a
`test:full` label present in the event, or a scheduled/manual/release checkpoint
for full validation. `full: 'false'` overrides event defaults, while missing
history and operational uncertainty still retain conservative execution.

The planner records its actual reasons once and carries them into its report.
The CLI explanation format 2 includes `selection_reasons`; `--explanation-format 1`
omits that field for older strict readers. The public `actions/test-impact@v1`
action defaults to format 1 for compatibility. A compatible reporter can request
`explanation-format: '2'`; CI-esta's wrapper does this automatically. Older
artifacts cannot identify a trigger they never recorded, so readers must say
that the reason is unavailable rather than infer it from the attempt number.

## GitHub Actions

This job uses the repository's composite action and runs the plan on the checked-out
head. Use the moving `v1` release tag and adapt dependency installation to
your project. The example assumes a uv project and passes the planned paths as
JSON, so spaces in filenames survive execution.

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
        uses: gigaverse-app/pytest-selective@v1
        with:
          config: .github/test-impact.json
          full-roots: tests
      - if: steps.impact.outputs.mode != 'none'
        run: uv sync --locked
      - if: steps.impact.outputs.mode != 'none'
        env:
          TEST_ROOTS: ${{ steps.impact.outputs.test_roots_json }}
        shell: bash
        run: |
          uv run --locked python - <<'PY'
          import json, os, subprocess, sys
          roots = json.loads(os.environ['TEST_ROOTS'])
          if not roots:
              raise SystemExit('Expected test roots for a nonempty plan')
          raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-p', 'no:selective', *roots]))
          PY
```

The action creates its own Python 3.14 planner environment. Your uv project
controls the test interpreter. `full-roots` must contain the complete roots, not
the previous selection. `base` defaults to the PR base or the push's previous
commit. Override it only when you have validated a different comparison base.

On a pull request, GitHub checks out a merge of the PR head into the base
branch's current tip, which can be newer than the PR's recorded base. Both
actions pass the PR head (`pr-head`) so the planner measures changes from that
merge's base-branch parent. Commits that landed on the base branch after the PR
was opened, such as a release's version bump, are then not counted as the PR's
own. A shallow checkout or any other event keeps `base`. Check out with
`fetch-depth: 0` to get the narrower plan.

Both file and lane actions default to `full: auto`:

| Trigger | Default |
| --- | --- |
| Ordinary PR or push, including reruns | Select affected work |
| Manual, schedule, release or reusable-workflow call | Full checkpoint |
| PR carrying `test:full` | Full checkpoint |
| Unknown event or unreadable required event metadata | Full checkpoint |

Use `full: 'true'` to always run everything, or `full: 'false'` to request
selection even for a manual experiment. Operational uncertainty still falls back
to full execution. Existing explicit expressions keep their behavior; remove a
copied standard expression to adopt the shared policy. Updating an action does
not add missing jobs, schedules, permissions or test dependency declarations.
GitHub reusable workflows retain the caller's event, so pass `full: 'true'` when
the reusable invocation itself must be a checkpoint.

| Planner outcome | Action behavior |
| --- | --- |
| `scoped` | Run selected files |
| `full` | Run complete configured roots |
| `none` | Skip pytest |
| Operational failure, such as missing Git history | Run `full-roots` |
| Invalid dependency declaration / unparseable Python | Fail with a diagnostic; fix the input |

Read the [action inputs](../actions/test-impact/action.yml) for cache
warming, shard planning, explanations, and optional first-party dependency pins.
Advanced base reuse requires proof that the reused revision passed the applicable
checks. Start with the PR base and full history.

## Parser resources and plugin registration

Large uncached batches (at least 256 unique Python blobs and 1 MB of source) use
up to four parser processes, bounded by available CPUs. They run the same parser
as serial analysis and never import the analyzed source. Small edits and cache
hits avoid worker startup. Set `PYTEST_SELECTIVE_PARSE_WORKERS=1` to use one
process, or choose an explicit worker count for your runner. If workers cannot
start or return a complete result, the planner retries serially.

Static `pytest_plugins` declarations are followed recursively, including single
module names, comma-separated strings and literal list extensions. Registered
plugins affect the whole pytest session. Computed declarations cause a full-run
fallback because their dependencies cannot be proven statically.

Put shared plugin registration in the root `conftest.py` when using independent
pytest shards. If a test module registers plugins, partial selection retains
that module and the shared shard planner keeps the selected tests together in
one process. CI-esta uses this planner too. This preserves fixture and hook
registration without executing the registering test multiple times.

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
[`plan-lanes`](../actions/plan-lanes/action.yml) or
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

An affected test selects its entire lane. A change whose imports reach every graph
test selects every lane holding graph tests, and no lane whose roots hold none (Bun or
Node tests, a build): other evidence selects those. A graph global input (an
environment file) still selects every lane. A lane's roots hold its tests, not its
inputs: another file under them (a README, notes, an unimported helper) selects the
lane only through the graph, and the plan names it as `unreferenced under root`.
Declare data that tests read, and let the read audit find undeclared reads. A
deleted test still selects its lane. Explicit lane inputs cover external
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
  "global_inputs": ["uv.lock", "pyproject.toml", "actions/**"]
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
`global_inputs`, which runs every lane first. The built-in policy includes
non-Markdown files under `.github/`, so a config with a job input must set
`global_inputs` explicitly.

### Documentation and default lane inputs

Unreferenced documentation changes select no tests. The whole-lane planner's
built-in global-input policy covers dependency/environment files and non-Markdown
files under `.github/`, including workflows, actions, helpers and extensionless
scripts. Files ending in `.md` or `.markdown` (case-insensitive) under `.github/`
do not trigger lanes merely because of their location. This applies to additions,
edits and deletions; removing or renaming an execution file still triggers lanes.

This default does not suppress dependencies. A `gv:test-dependency` comment,
dependency sidecar, central dependency rule, or lane `inputs` entry still selects
the consuming tests or lanes. Explicit `global_inputs` globs also retain their
full meaning: declaring `[".github/**"]` includes Markdown and runs every lane.

Two lists decide which changes run every lane. `graph.global_inputs` is the
environment-file list, and the only place to narrow it: its built-in default matches
`*requirements*.txt` and `*requirements*.in` anywhere, including a documentation site's
`documentation/requirements.txt`, so such a repository should set `graph.global_inputs`
to its real environment files. Top-level `global_inputs` lists CI execution inputs; when
omitted it is every non-Markdown file under `.github/` plus `graph.global_inputs`. An
explicit top-level list replaces only the CI part: a change matching `graph.global_inputs`
still runs every lane, because it reaches every test. Inputs and
rules match like gitignore patterns: `dir/**/*.py` matches `dir/x.py` and
`dir/a/x.py`, and `*` also crosses `/`. [Audit a documentation-only pull request](tutorials/skip-unrelated-ci.md#audit-what-a-documentation-only-pull-request-still-runs)
before claiming the route works.

Omit `global_inputs` or use `null` for the built-in policy. An explicit list
replaces that policy; `[]` disables lane-level global inputs while graph-level
dependencies and environment inputs still apply. Serialized `LaneConfig` defaults
now preserve `global_inputs: null` instead of expanding the old `.github/**` glob.
Existing configs that explicitly contain that glob keep their declared behavior;
remove the override to adopt the new default. Full checkpoints and operational
failure fallbacks still run every lane. Invalid declarations still fail visibly.

The planner only selects tests and lanes. Workflow commands outside its admission
conditions, such as package-install smoke checks, still run independently. Wire
those runtime checks to the relevant lane decision; keep README metadata checks
when the README is embedded in the built package.

The action returns a `lanes` JSON object. Expose it as a planning-job output,
then gate each expensive job with `always() && !cancelled()` and either a true
lane value **or a failed planning job**. This preserves tests if planning fails.
`always()` also ignores the job's other needs, so check their results explicitly.

GitHub reports a job skipped by `if:` as a passing required check. Make one aggregate
job per workflow the required check and run
[`actions/validation-gate`](../actions/validation-gate/action.yml) in it, with
`needs: ${{ toJSON(needs) }}`, the planner's `lanes` and a `lane-jobs` map from each
gated job to its lanes. It fails unless each prerequisite succeeded or was skipped while
the planner succeeded and every mapped lane is `false`; a failed planner fails it.

Never gate a job that a publish or deploy job `needs:`, directly or transitively:
skipping it skips publishing. Leave it ungated, or plan inside the job with
`continue-on-error: true` and admit only its expensive steps, as the `distributions`
job in this repository's CI does. Gate every other job that installs, builds or tests. A branch's first push has no previous commit, so
`on: push` for every branch runs every lane once per new branch; prefer pull-request
triggers plus pushes to the default branch.
The default event policy handles manual/release checkpoints, schedules and
`test:full`. Ordinary PRs and main pushes use dependency selection.
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

## Split whole lanes by test filename

Lanes sharing a directory can partition its tests with `test_patterns` and
`exclude_patterns`. Both match repository-relative POSIX paths using the same
globs as lane inputs; `*` also matches path separators. Roots still limit the
search. The defaults include every test under the roots and exclude none.

```json
{
  "unit": {"roots": ["tests"], "exclude_patterns": ["*_integration.py"]},
  "integration": {"roots": ["tests"], "test_patterns": ["*_integration.py"]}
}
```

Put these entries under `lanes` in the lane configuration. A source dependency
still selects every lane containing an affected test. Deleted tests use their
base-revision membership; an affected test claimed by no lane causes a full
fallback. Explicit inputs and full checkpoints are unaffected by these filters.

Same-named modules in independent module roots are unrelated unless an import
connects them. An actual ambiguous bare import conservatively retains every
possible target. Use qualified imports to make independent demo modules
unambiguous; selection does not guess a runtime import order.
# Graph cache restoration

The test-impact action saves its disposable graph cache under the analyzed `head`,
runner OS, Python 3.14 runtime and workflow ref. Restores prefer that head and
previous work on the same PR, then exact base revisions from the default branch.
Exact legacy revision keys are tried before broader default-branch and legacy
OS fallbacks, so existing caches can seed the new namespace. Each run can save
its newly learned graphs without overwriting an immutable earlier cache.

Keys only choose download candidates. GraphCache still validates content IDs,
parser versions, configuration and checksums; a missing or unusable cache is
rebuilt. Cache lookup failures do not prevent selection.

The action also writes `test-impact-timings.json` and prints its contents to the
log. Its whole-action clock includes runtime setup, cache restore/save, Git fetch,
both selection candidates, explanation generation/upload and the floor check.
The final timing-report write and GitHub runner orchestration outside the action
are excluded; use the enclosing GitHub step duration for that outer boundary.
`affected --timings-output PATH` separately measures CLI setup, each candidate,
selection policy, explanation, output/shards and cache close. Python process
startup and imports belong to the action's outside-CLI time. Existing report
`elapsed_seconds` remains the winning candidate's analysis time, now labeled
explicitly in the summary. Timings are diagnostic and never authorize test skips.

