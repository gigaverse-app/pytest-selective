---
name: pytest-selective
description: Set up pytest-selective in a Python repository's CI end to end, so documentation and unrelated changes skip expensive test jobs while code changes keep complete coverage. Use to adopt it (lane config, planner job, gate, routing tests, measured before/after), to narrow broad CI triggers, or to check that docs-only changes skip unrelated tests.
license: Apache-2.0
---

# Set up pytest-selective in a repository

You are a coding agent adopting pytest-selective in the repository you are working in. This file is the whole
procedure. Follow it in order and open one pull request. Links are for depth only; you should not need them.

pytest-selective reads a Git change, follows Python imports and declared non-Python inputs through both the base and
head trees, and decides which CI **lanes** (groups of jobs) the change can affect. A planner job publishes that
decision; each expensive job runs only when its lane is affected **or planning failed**; one gate job accepts a skipped
job only when a successful plan said its lanes were unaffected. An affected lane always runs complete, with its
matrix, services and coverage checks unchanged.

**Ground rules**

- Work on a new branch and open a draft pull request. Follow the repository's AGENTS.md, CONTRIBUTING, pull request
  template and any AI-contribution policy (some forbid agent-authored pull requests or require disclosure); they win
  over this file on style. If a policy forbids this work, stop and say so.
- Never trade coverage for speed: do not delete tests, drop matrix entries, lower coverage floors or change what a
  release publishes. Selection only decides whether a job starts.
- Stop and tell the human, with the exact step, when something needs a repository setting: required checks, rulesets,
  labels, secrets. Do not change them yourself.
- Pass `--repo "$REPO"` to every `gh` command. In a clone of a fork, `gh` otherwise picks the upstream repository.
- If a command fails, report the exact command and its error. Do not make a failure pass by widening or emptying
  inputs, ignoring a test directory, or removing a job from the gate.

## 1. Preflight

Run these and note the answers. Every later step uses them.

```bash
REPO=OWNER/NAME     # the repository you will open the pull request in: check `git remote -v`; in a fork, the fork
gh repo view --repo "$REPO" --json defaultBranchRef -q .defaultBranchRef.name           # DEFAULT below
ls AGENTS.md CLAUDE.md CONTRIBUTING.md .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE* \
   .pre-commit-config.yaml zizmor.yml .github/zizmor.yml 2>/dev/null
ls pyproject.toml setup.cfg setup.py tox.ini noxfile.py pytest.ini uv.lock poetry.lock pdm.lock Pipfile.lock \
   requirements*.txt requirements/ */requirements*.txt 2>/dev/null
grep -nE 'testpaths|addopts|\[tool.pytest|\[pytest\]|\[tool:pytest\]' pyproject.toml setup.cfg tox.ini pytest.ini 2>/dev/null
grep -rhE '^\s*-?\s*uses:' .github/workflows | sort | uniq -c       # how actions are pinned
grep -nE '^on:|^  [a-z_]+:$|branches|paths|needs:|matrix:|services:|^\s+if:' .github/workflows/*.y*ml
gh run list --repo "$REPO" --branch DEFAULT --limit 10 --json databaseId,workflowName,event,conclusion
gh api "repos/$REPO/branches/DEFAULT/protection/required_status_checks" --jq .contexts   # 403/404: ask the human
```

Record:

- **Conventions**: commit and PR title style, changelog rules, AI policy, pre-commit hooks.
- **Packaging tool**: uv project, Poetry, PDM, Hatch with tox or nox, or plain pip requirements/extras. It decides how
  you run the planner locally and how routing tests install (step 6). CI planning itself installs nothing in the
  project: the actions bring their own Python 3.14 planner.
- **Pinning policy**: actions pinned to 40-character commit SHAs (often enforced by zizmor's `unpinned-uses` or a
  `pinact` hook), to version tags, or to moving major tags.
- **Test jobs**: every job that installs the project, builds it, smoke-tests it, or runs tests or benchmarks, with
  its matrix size, services, coverage floors and typical duration (`gh run view RUN --repo "$REPO" --json jobs`).
- **Publish paths**: jobs that publish or deploy (PyPI, Test PyPI, Pages, containers, releases) and every job they
  `needs:`, directly or transitively. Step 4.4 keeps these paths unchanged.
- **Triggers**: whether `push` runs for every branch, and any `branches:`/`paths:` filters.
- **Existing gate**: an aggregate job (`all-green`, `alls-green`, `check`) and the required check names.

If CI already finishes in a couple of minutes, or nearly every change touches source code, say so in your report:
selection saves little there. Continue only if the human's request still stands.

### One version, used everywhere

Resolve the latest release once:

```bash
TAG=$(gh release view --repo gigaverse-app/pytest-selective --json tagName -q .tagName)   # for example v1.1.0
VERSION=${TAG#v}
SHA=$(gh api "repos/gigaverse-app/pytest-selective/commits/$TAG" --jq .sha)
```

The rule: every action and the package you add come from that one release. The package is
`pytest-selective==$VERSION` (or `>=$VERSION,<2` where the repository uses ranges with a lock). Each action is
`gigaverse-app/pytest-selective/actions/NAME@<ref>`, where `<ref>` follows the repository's pinning policy:
`@$SHA # $TAG` if it pins commit SHAs, otherwise `@$TAG`. Update them together. The moving `@v1` tag also works,
but it runs a newer planner than the version your routing tests install.

`gh api .../commits/TAG` resolves annotated tags to the commit; `git/ref/tags/TAG` would return the tag object.
Version-matched source files are at `https://github.com/gigaverse-app/pytest-selective/blob/$TAG/...`.

## 2. Choose lanes

A lane is a set of jobs that must run together, and the test files (roots) and other inputs that make them run.
Start with as few lanes as the jobs need:

| Job kind | Lane |
| --- | --- |
| The test matrix (all Python versions, PyPy, free-threaded, OSes) | `tests`: roots = every test directory |
| Benchmarks (CodSpeed, pytest-benchmark) over a subset of tests | `bench`: roots = that subset; it may overlap `tests` |
| Build, `twine check`, install/import smoke | `package`: no roots; inputs = package sources, metadata and an embedded README |
| Your routing tests (step 6) | `routing`: roots = their directory |
| Integration tests with services, or another suite run separately | its own lane with its own roots |

Keep these unconditional: the planner, lint, type checking, documentation builds, link checks and the gate.

Optionally, developers can also run only affected tests locally with `pytest --selective` after adding
`pytest-selective` to the test dependencies (`uv add --dev`, `poetry add --group dev`, a `tests` extra, a tox `deps`
line or a nox `session.install`). CI does not need this.

## 3. Write `.github/test-lanes.json`

```json
{
  "graph": {
    "module_roots": ["src", "."],
    "test_roots": ["tests", "ci_tests"],
    "global_inputs": ["pyproject.toml", "tox.ini", "requirements/tests.txt"]
  },
  "lanes": {
    "tests": {"roots": ["tests"]},
    "bench": {"roots": ["tests/benchmarks"]},
    "package": {"inputs": ["src/**", "pyproject.toml", "README.md", "LICENSE"]},
    "routing": {"roots": ["ci_tests"]}
  },
  "global_inputs": [".github/test-lanes.json", ".github/workflows/test.yml", "pyproject.toml", "tox.ini"]
}
```

Adapt every path; this is a shape, not an inventory. The rules:

- **`graph.module_roots`** are the directories imports resolve from (`src` for a src layout, `.` for a flat one).
  **`graph.test_roots`** list every directory holding tests, including the routing tests.
- **Every test file must sit under some lane's `roots`.** An affected test outside all lanes runs every lane
  (`full-suite fallback: unmapped affected tests`). A root may be a directory or a single file. Roots may overlap: a
  lane runs when any test under its roots is affected, so a benchmark lane over `tests/benchmarks` runs only for
  changes that reach a benchmark, while `tests` runs for those too.
- **Lane `inputs`** are globs of non-test files whose change must run that lane. They match like gitignore:
  `dir/**/*.py` matches `dir/x.py` and `dir/a/x.py`. Name execution files; never a directory that also holds prose
  (`examples/**` runs the lane for an example's README; use `examples/**/*.py`). A lane without roots runs only on its
  inputs, on global inputs, or when a change reaches every test.
- **`graph.global_inputs`** are the environment files whose change can affect every test, and the only place to narrow
  them. Omitted, the built-in list applies: `pyproject.toml`, `setup.cfg`, `setup.py`, `tox.ini`, `pytest.ini`,
  `pytest.toml`, `uv.lock`, `poetry.lock`, `pdm.lock`, `pixi.lock`, `Pipfile`, `Pipfile.lock`, `*requirements*.txt`,
  `*requirements*.in`, `requirements*.lock`, `pylock*.toml`, `requirements/**` and `*constraints*.txt`, anywhere in the
  tree. Set it explicitly when the repository has a requirements file the tests do not use (a docs site's
  `docs/requirements.txt`, a type-check or release requirements file), and add files the list lacks, such as
  `noxfile.py` or a `constraints/` directory.
- **Top-level `global_inputs`** are CI execution files whose change must run every lane. Omitted, they are every
  non-Markdown file under `.github/` plus `graph.global_inputs`, so a `dependabot.yml` or release-workflow edit would
  run everything. An explicit list replaces that: name the lane config, the workflows that run lane jobs, local
  actions and CI helper scripts. Environment files from `graph.global_inputs` run every lane either way.
- To make a workflow edit run only the lane whose job changed, name the job as a lane input instead:
  `".github/workflows/test.yml#tests"`. Only a change to that job's parsed YAML, or to settings every job inherits,
  runs the lane; comments do not. The workflow file must then not match top-level `global_inputs`.

Add `.test-impact/` to `.gitignore`: the planner keeps its graph cache there.

**Collection policy.** If pytest configuration exists (`[tool.pytest.ini_options]`, `pytest.ini`, a `[pytest]` or
`[tool:pytest]` section, `tox.ini`), the planner runs every lane until you record its fingerprints
(`full-suite fallback: pytest configuration changed; review collection policy and refresh its fingerprints`). Review
the pytest settings and collection hooks, commit the config, then:

```bash
python -c "import json; print(json.dumps(json.load(open('.github/test-lanes.json'))['graph']))" > /tmp/graph.json
uv run --no-project --with "pytest-selective==$VERSION" \
  pytest-selective fingerprints --config /tmp/graph.json --head HEAD
```

Copy the printed object into `graph.pytest_policy` and commit. Without uv, run the same commands in a virtual
environment after `python -m pip install "pytest-selective==$VERSION"`. When pytest settings change later, the planner
falls back to every lane until someone reviews and refreshes the fingerprints.

### Prove the config locally

On a throwaway branch, commit one probe edit at a time and plan it against the default branch:

```bash
uv run --no-project --with "pytest-selective==$VERSION" \
  python -m pytest_selective.ci --config .github/test-lanes.json --base origin/DEFAULT --head HEAD
```

Expected: JSON with `lanes` (one boolean per lane), `reason` and `lane_reasons`. A README edit gives every lane
`false` (or only `package`, when the build embeds the README) with `no affected tests or changed inputs`; a source
edit selects the lanes of the tests that import it (`affected test: tests/test_x.py`); a lockfile or workflow edit
selects every lane (`global input: ...`). Probe a docs page, each requirements file, a source module, a test, a
benchmark, a nested file in each directory you narrowed, and each workflow. If a source edit selects every lane
(`all graph test files affected`), every test reaches it, often through a package `__init__.py`: correct, not a misroute.

## 4. Wire the workflows

### 4.1 The planner job

Add to each workflow that runs lane jobs, using the repository's own pin for `actions/checkout`:

```yaml
  select-tests:
    runs-on: ubuntu-latest
    outputs:
      lanes: ${{ steps.plan.outputs.lanes }}
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0               # the planner needs the base commit
          persist-credentials: false
      - id: plan
        uses: gigaverse-app/pytest-selective/actions/plan-lanes@REF   # step 1's ref
        with:
          config: .github/test-lanes.json
```

`full` defaults to `auto`: pull requests and pushes select; `workflow_dispatch`, `workflow_call`, `schedule` and
`release` events, and pull requests labelled `test:full`, run every lane. Reruns keep the first attempt's selection.
Keep (or propose) a scheduled full run.

### 4.2 Gate each lane job

```yaml
  tests:
    needs: select-tests
    if: >-
      ${{ always() && !cancelled() && (needs.select-tests.result != 'success' ||
          fromJSON(needs.select-tests.outputs.lanes).tests) }}
```

`always()` lets the condition run when the planner failed, and the failed-planner branch then runs the job: a broken
plan must never become a green skip. The condition applies before the matrix expands, so the whole matrix skips
together. A job with other needs must check them itself, because `always()` also ignores their failure:
`needs: [select-tests, build]` with `... && needs.build.result == 'success' && (...)`.

### 4.3 Triggers

- **New-branch pushes.** With `on: push` for every branch, a branch's first push has no previous commit (`before` is
  `0000000...`), so the planner runs every lane: a full run per new branch. Prefer `pull_request` plus
  `push: branches: [DEFAULT]`. If the repository wants branch pushes, give the planner a base for new branches:
  `base: ${{ github.event.pull_request.base.sha || (github.event.created && format('origin/{0}', github.event.repository.default_branch)) || github.event.before }}`.
  Changing triggers is a behavior change: say so in the pull request.
- **`branches:` filters.** A probe pull request opened against your adoption branch does not start workflows filtered
  to `pull_request: branches: [main]`. Prove those workflows with routing tests and local plans, and say in the report
  that their hosted probe waits for the merge.

### 4.4 Jobs on a publish path

If a publish or deploy job `needs:` a job you gate, skipping that job also skips publishing. Do not change what
publishes. Use one of these, in order of preference:

1. Leave publish workflows and every job they need ungated. Gate only pull-request verification.
2. Keep the needed job running on every other event:
   `${{ always() && !cancelled() && (github.event_name != 'pull_request' || needs.select-tests.result != 'success' || fromJSON(needs.select-tests.outputs.lanes).package) }}`.
3. Admit steps, not the job: the job always runs and succeeds, so its dependents still run, and only its expensive
   steps skip. Plan inside the job and let a failed plan run everything:

```yaml
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: plan
        continue-on-error: true          # a failed plan runs the steps below
        uses: gigaverse-app/pytest-selective/actions/plan-lanes@REF
        with:
          config: .github/test-lanes.json
          artifact-name: ''
      - if: ${{ steps.plan.outcome != 'success' || fromJSON(steps.plan.outputs.lanes).package }}
        run: python -m build && python -m twine check --strict dist/*
```

Keep the steps that produce what the publish job downloads unconditional.

## 5. Add the gate

GitHub reports a job skipped by `if:` as passing a required check. One aggregate job per workflow becomes the required
check:

```yaml
  gate:
    name: Test gate                       # the required check name
    needs: [select-tests, lint, tests, bench, package, routing]   # every other job in this workflow
    if: ${{ !cancelled() }}
    runs-on: ubuntu-latest
    steps:
      - uses: gigaverse-app/pytest-selective/actions/validation-gate@REF
        with:
          needs: ${{ toJSON(needs) }}
          lanes: ${{ needs.select-tests.outputs.lanes || '{}' }}
          lane-jobs: '{"tests":["tests"],"bench":["bench"],"package":["package"],"routing":["routing"]}'
```

It passes only when every prerequisite succeeded, or was skipped while the planner succeeded and every lane mapped to
that job is `false`. A failed, cancelled or skipped planner, a failed job, or a skip of an unmapped job fails it. It
installs nothing. If the repository already has an aggregate job, keep its name and replace its logic with this step.
`actions/validation-gate` exists from the release after 1.0.0; if
`gh api "repos/gigaverse-app/pytest-selective/contents/actions/validation-gate/action.yml?ref=$TAG"` returns 404, use
`gigaverse-app/ci-esta/actions/validation-gate@v1` with the same inputs.

## 6. Add routing tests

Routing tests replay real Git changes through the committed config and check the workflow wiring. Put them in their
own directory (`ci_tests/`, unless the repository has a convention), run them in their own `routing` job, and install
only what they need there:

```yaml
  routing:
    needs: select-tests
    if: >-
      ${{ always() && !cancelled() && (needs.select-tests.result != 'success' ||
          fromJSON(needs.select-tests.outputs.lanes).routing) }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - uses: actions/setup-python@v7
        with:
          python-version: '3.13'
      - run: python -m pip install "pytest-selective==VERSION"   # brings pytest and PyYAML
      - run: python -m pytest ci_tests -q
```

- Keep `pytest-selective` out of the main test matrix and its requirements. Make sure the main test command does not
  collect `ci_tests/` (`testpaths`, or `--ignore=ci_tests`).
- If mypy or pyright checks every directory, exclude `ci_tests/` or give it its own check. Adding `pytest-selective`
  to a type-check requirements file makes that file an environment input (`*requirements*.txt`), so its next bump
  would run every lane; list it in `graph.global_inputs` only if tests really use it.
- pre-commit and prek only check tracked files: `git add` new files before running the hooks.

Start from this file, `ci_tests/test_ci_routing.py`, and adapt `FIXTURE`, the rows and the workflow path:

```python
"""Route real Git changes through the committed lane config (pytest-selective)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pytest_selective.ci import LaneConfig, plan

ROOT = Path(__file__).resolve().parents[1]
CONFIG = LaneConfig.model_validate_json((ROOT / ".github/test-lanes.json").read_text(encoding="utf-8"))
EVERY = dict.fromkeys(CONFIG.lanes, True)
NONE = dict.fromkeys(CONFIG.lanes, False)
# Real files the graph needs, plus every file whose collection policy is fingerprinted.
FIXTURE = ["src/toy/__init__.py", "src/toy/core.py", "src/toy/other.py", "tests/test_core.py", "tests/test_other.py"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path) -> str:
    git(repo, "add", "-A")
    identity = ["-c", "user.name=routing", "-c", "user.email=routing@example.com", "-c", "commit.gpgsign=false"]
    git(repo, *identity, "commit", "--quiet", "--no-verify", "--allow-empty", "--message", "routing probe")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet")
    for path in {*FIXTURE, *CONFIG.graph.pytest_policy}:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, tmp_path / path)
    return tmp_path


@pytest.mark.parametrize(
    "path, expected",
    [
        ("README.md", {**NONE, "package": True}),
        ("docs/index.md", NONE),
        ("docs/requirements.txt", NONE),  # the docs site's environment, not the tests'
        ("tests/test_other.py", {**NONE, "tests": True}),
        ("src/toy/other.py", {**NONE, "tests": True, "package": True}),
        ("tests/benchmarks/test_bench.py", {**NONE, "tests": True, "bench": True}),
        ("tox.ini", EVERY),
        (".github/test-lanes.json", EVERY),
        (".github/workflows/test.yml", EVERY),
    ],
)
def test_a_change_runs_exactly_its_lanes(repo: Path, path: str, expected: dict[str, bool]) -> None:
    base = commit(repo)
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write("\n# routing probe\n")
    result = plan(repo, CONFIG, base, commit(repo))
    assert result.lanes == expected, result.lane_reasons


def test_missing_history_and_full_checkpoints_run_every_lane(repo: Path) -> None:
    head = commit(repo)
    assert plan(repo, CONFIG, "0" * 40, head).lanes == EVERY  # e.g. a new branch's first push
    assert plan(repo, CONFIG, head, head, full=True).lanes == EVERY


def test_the_gate_guards_every_job_and_lane_jobs_run_when_planning_fails() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8"))
    assert "pull_request" in workflow[True]  # PyYAML reads the `on:` key as the boolean True
    jobs = workflow["jobs"]
    (step,) = [step for step in jobs["gate"]["steps"] if "validation-gate" in step.get("uses", "")]
    lane_jobs = json.loads(step["with"]["lane-jobs"])
    assert set(jobs["gate"]["needs"]) == set(jobs) - {"gate"}
    assert {lane for lanes in lane_jobs.values() for lane in lanes} <= set(CONFIG.lanes)
    for job, lanes in lane_jobs.items():
        condition = " ".join(jobs[job]["if"].split())
        assert "always() && !cancelled()" in condition, job
        assert "needs.select-tests.result != 'success'" in condition, job
        assert all(f"fromJSON(needs.select-tests.outputs.lanes).{lane}" in condition for lane in lanes), job
```

Add a row for every directory you narrowed, every requirements file, each workflow and each lane. A row appends a
comment; a `<workflow>#<job>` input ignores comments, so edit the job itself in that row. Run the file locally with
`uv run --no-project --with "pytest-selective==$VERSION" pytest ci_tests -q` and commit it.

## 7. Prove it on hosted CI

1. Push the branch and open the draft pull request. Its first run changes workflows, so every lane runs: that is the
   full baseline, not a misroute.
2. Branch from the adoption branch, edit only a README line and a docs page, push, and open a probe pull request
   against the adoption branch (mind 4.3's `branches:` filters). List what executed:

   ```bash
   gh run list --repo "$REPO" --branch PROBE_BRANCH --json databaseId,workflowName,conclusion
   gh run view RUN --repo "$REPO" --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
   ```

   Expected: the planner, lint, docs, the `package` lane only if the build embeds the README, and the gate ran; every
   other lane job is `skipped`; the gate succeeded. Anything else that installs, builds or tests is a trap: gate it.
3. Repeat with a one-line source change: its lanes run in full, the rest skip.
4. Keep the probe pull requests open until you have measured, then close them without merging and delete their
   branches.

## 8. Measure

Compare a selected run with a full control **at the same head**:

- Selected: the docs-only probe's runs.
- Full control: ask the human to create the `test:full` label if `gh label list --repo "$REPO"` lacks it. Add it to
  the probe pull request, then close and reopen the pull request: the `reopened` event plans with the label and runs
  every lane. Adding a label alone starts nothing unless a workflow lists `labeled`. Or run
  `gh workflow run WORKFLOW --repo "$REPO" --ref PROBE_BRANCH` where the workflow has `workflow_dispatch`; it runs
  every lane but checks out the branch head instead of the pull request's merge commit, so record both SHAs. A rerun
  is not a control: it keeps the selection.

```bash
gh run list --repo "$REPO" --commit HEAD_SHA --json databaseId,workflowName,event,conclusion,createdAt
uv run --no-project https://raw.githubusercontent.com/gigaverse-app/pytest-selective/main/scripts/measure_ci_runs.py \
  "$REPO" --selected RUN_A RUN_B --full RUN_C RUN_D --output comparison.json
```

List every workflow run of each side (it adds runner-seconds across workflows and spans elapsed time from the first
run's creation to the last job's end). The script is read-only and needs an authenticated `gh`. It rejects runs that
are unfinished or have a failed job; pass `--expected-failure JOB` only for a job that fails on purpose. Expected
output: a JSON file with `selected` and `full` (each with `runner_seconds`, `elapsed_seconds`, `executed_jobs`,
`workflows` and per-run job records), `runner_seconds_saved` and `runner_seconds_reduction_percent`. One pair is an
observation, not an average or a bill. Without live CI access, deliver the config, routing tests and these commands,
and label hosted impact unmeasured.

## 9. Stop for the human

Leave these to the human and list them in the pull request:

- Make each workflow's gate job a required check, and remove required checks for jobs that can now be skipped.
- Create the `test:full` label, if it does not exist.
- Approve any trigger change from 4.3 and a scheduled full run.
- Merge. Then a docs-only pull request against the default branch proves the workflows that 4.3's filters hid.

## 10. Report

Use this in the pull request body, filled in:

```markdown
## pytest-selective adoption

pytest-selective vX.Y.Z: actions at `<sha>` (`# vX.Y.Z`), routing tests install `pytest-selective==X.Y.Z`.

| Lane | Jobs it admits | Roots and inputs |
| --- | --- | --- |
| tests | test (N matrix jobs) | tests/ |

### Measured at head `<sha>`

| | Full control | Selected (docs-only) |
| --- | ---: | ---: |
| Executed jobs | | |
| Runner-seconds | | |
| Elapsed seconds | | |

Runs: [full](https://github.com/OWNER/NAME/actions/runs/RUN_ID), [selected](https://github.com/OWNER/NAME/actions/runs/RUN_ID). One pair, not an average or a bill.

### Evidence
- N routing tests: docs, requirements, source, tests, benchmarks, workflows, missing history, full checkpoint.
- Probe pull requests: [docs-only](https://github.com/OWNER/NAME/pull/N), [source](https://github.com/OWNER/NAME/pull/N).

### For you to decide
- Required check: `Test gate` replaces ...
- Label `test:full`; trigger change; scheduled full run.

### Not done or not verified
- ...
```

For depth: [configuration reference](https://pytest-selective.readthedocs.io/en/latest/docs/configuration/),
[CI guide](https://pytest-selective.readthedocs.io/en/latest/docs/ci/),
[documentation-only audit](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/skip-unrelated-ci/),
[declaring non-Python inputs](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/sidecar-dependencies/),
[guarantees and limits](https://pytest-selective.readthedocs.io/en/latest/docs/evidence/).
