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
- Name the repository on every `gh` command; in a clone of a fork, `gh` otherwise picks the upstream repository.
  `gh pr`, `gh run`, `gh workflow`, `gh label`, `gh secret` and `gh release` take `--repo "$REPO"`; `gh repo view`
  takes it as an argument (`gh repo view "$REPO"`); `gh api` takes it in the path (`repos/$REPO/...`).
- Keep scratch files in `.test-impact/` (ignored, step 3), not `/tmp`: native Windows Python cannot open Git Bash's
  `/tmp`.
- If a command fails, report the exact command and its error. Do not make a failure pass by widening or emptying
  inputs, ignoring a test directory, or removing a job from the gate.

## 1. Preflight

Run these and note the answers. Every later step uses them.

```bash
REPO=OWNER/NAME     # the repository you will open the pull request in: check `git remote -v`; in a fork, the fork
gh repo view "$REPO" --json defaultBranchRef -q .defaultBranchRef.name                  # DEFAULT below
gh api "repos/$REPO" --jq '.parent.full_name // "not a fork"'                           # UPSTREAM below
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

A fresh fork has no runs yet. Read the typical jobs and durations from UPSTREAM instead, read-only: the same
`gh run list` and `gh run view` commands with `--repo UPSTREAM`. Never push, label or dispatch there.

Record:

- **Conventions**: commit and PR title style, changelog rules, AI policy, pre-commit hooks. When the pull request
  template names a CONTRIBUTING, CODE_OF_CONDUCT or security file the repository lacks, read the owner's organization
  default from its `.github` repository (in a fork, the upstream owner's):
  `gh api "repos/OWNER/.github/contents/CONTRIBUTING.md" --jq .content | base64 -d`.
- **Packaging tool**: uv project, Poetry, PDM, Hatch with tox or nox, or plain pip requirements/extras. It decides how
  you run the planner locally and how routing tests install (step 6). CI planning itself installs nothing in the
  project: the actions bring their own Python 3.14 planner.
- **Pinning policy**: actions pinned to 40-character commit SHAs (often enforced by zizmor's `unpinned-uses` or a
  `pinact` hook), to version tags, or to moving major tags.
- **Test jobs**: every job that installs the project, builds it, smoke-tests it, or runs tests or benchmarks, with
  its matrix size, services, coverage floors and typical duration (`gh run view RUN --repo "$REPO" --json jobs`).
- **Publish paths**: jobs that publish or deploy (PyPI, Test PyPI, Pages, containers, releases) and every job they
  `needs:`, directly or transitively. Step 4.4 keeps these paths unchanged.
- **Test workflows**: the file name of each workflow that runs tests (`test.yml`, `tests.yaml`, `ci.yml`, ...).
  Below, `test.yml` stands for `<the repo's test workflow>`: write the real names in the config, the routing test and
  the report.
- **Triggers**: whether `push` runs for every branch, and any `branches:`, `paths:` or `paths-ignore:` filters (4.3
  removes path filters from gated workflows).
- **Existing gate**: an aggregate job (`all-green`, `alls-green`, `check`) and the required check names.

If CI already finishes in a couple of minutes, or nearly every change touches source code, say so in your report:
selection saves little there. Continue only if the human's request still stands.

### Which version

Reference the actions by the moving major tag, `gigaverse-app/pytest-selective/actions/NAME@v1`: planner fixes reach
the repository without a pull request per release. The measurement script (step 8) comes from `v1` too. Resolve the
latest release once for the package:

```bash
TAG=$(gh release view --repo gigaverse-app/pytest-selective --json tagName -q .tagName)   # for example v1.1.0
VERSION=${TAG#v}
```

Local commands use `pytest-selective==$VERSION`; the routing-test job (step 6) installs `pytest-selective>=$VERSION,<2`,
so it follows the same major version as `@v1`. uv caches the package index, so a release published minutes ago can
be missing (`No solution found`, `pytest-selective==X.Y.Z` unsatisfiable): the local commands below pass
`--refresh-package pytest-selective`. With pip, add `--no-cache-dir`.

Only when the repository's tooling rejects tags (zizmor's `unpinned-uses`, a `pinact` hook, or an all-SHA policy its
CI enforces) pin the release instead: `@$SHA # $TAG` on every action, with
`SHA=$(gh api "repos/gigaverse-app/pytest-selective/commits/$TAG" --jq .sha)` (this resolves an annotated tag to its
commit; `git/ref/tags/TAG` would return the tag object), and `pytest-selective==$VERSION` in the routing job. Update
them together.

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

Keep these unconditional: the planner, lint, type checking, documentation builds, link checks, the gate, and every
job a publish or deploy job needs (step 4.4). Every other job that installs, builds or tests the project is gated.

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
    "tests": {"roots": ["tests"], "inputs": ["src/toy/*.c", "src/toy/*.pyi"]},
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
- **Non-Python sources are not imports.** A C extension (`_speedups.c`), Cython (`.pyx`, `.pxd`), type stubs
  (`.pyi`), templates or data files the tests read: the graph does not see them unless a test opens them by literal
  path. Add each as an input of the lanes that build or test it, as exact globs
  (`"tests": {"roots": ["tests"], "inputs": ["src/pkg/*.c", "src/pkg/*.pyi"]}`) or the package directory (`src/**`)
  when every file there matters, and give each a routing row (step 6).
- **`graph.global_inputs`** are the environment files whose change can affect every test, and the only place to narrow
  them. Omitted, the built-in list applies: `pyproject.toml`, `setup.cfg`, `setup.py`, `tox.ini`, `pytest.ini`,
  `pytest.toml`, `uv.lock`, `poetry.lock`, `pdm.lock`, `pixi.lock`, `Pipfile`, `Pipfile.lock`, `*requirements*.txt`,
  `*requirements*.in`, `requirements*.lock`, `pylock*.toml`, `requirements/**` and `*constraints*.txt`, anywhere in the
  tree. Root-level files match too: `requirements-mypy.txt`, `requirements-lint.txt` or `docs-requirements.txt` each
  run every lane, so a Dependabot bump of mypy would start the whole test matrix. Set the list explicitly whenever the
  repository has a requirements file the tests do not install (a docs site's, a type-check, lint or release one),
  naming only what the tests do use, and add files the built-in list lacks, such as `noxfile.py` or a `constraints/`
  directory. For example, tests installed from `pyproject.toml` through tox, beside a `requirements-mypy.txt`:
  `"graph": {"global_inputs": ["pyproject.toml", "tox.ini"], ...}`. Prove it with a routing-test row
  (`("requirements-mypy.txt", NONE)`, step 6).
- **Top-level `global_inputs`** are CI execution files whose change must run every lane. Omitted, they are every
  non-Markdown file under `.github/` plus `graph.global_inputs`, so a `dependabot.yml` or release-workflow edit would
  run everything. An explicit list replaces that: name the lane config, the workflows that run lane jobs, local
  actions and CI helper scripts. Environment files from `graph.global_inputs` run every lane either way.
- To make a workflow edit run only the lane whose job changed, name the job as a lane input instead:
  `".github/workflows/test.yml#tests"`. Only a change to that job's parsed YAML, or to settings every job inherits,
  runs the lane; comments do not. The workflow file must then not match top-level `global_inputs`.

Add `.test-impact/` to `.gitignore`: the planner keeps its graph cache there.

**Collection policy.** If pytest configuration exists (`pyproject.toml`, `pytest.ini`, `pytest.toml`, a `tox.ini`
with `[pytest]`, a `setup.cfg` with `[tool:pytest]`), the planner runs every lane until you record its fingerprints
(`full-suite fallback: pytest configuration changed (pyproject.toml); review collection policy and refresh its
fingerprints: ...`). Review
the pytest settings and collection hooks, commit the config, then:

```bash
uv run --refresh-package pytest-selective --no-project --with "pytest-selective==$VERSION" \
  pytest-selective fingerprints --config .github/test-lanes.json --head HEAD
```

Copy the printed object into `graph.pytest_policy` and commit. Every `pytest-selective` command (`fingerprints`,
`explain`, `affected`, `run`) takes the lane config itself as `--config`, so the policy you record is the one in use.
Releases up to 1.2.0 need a derived file instead: `pytest-selective file-config --lanes .github/test-lanes.json
--output .test-impact/graph.json` (it needs top-level `global_inputs`), passed as `--config .test-impact/graph.json`.
Re-run it after every lane-config change, recording `pytest_policy` included, or `explain` keeps failing with
`pytest configuration changed`. Releases up to 1.1.1 also print a `tox.ini` or
`setup.cfg` that has no pytest section (pytest ignores it); keeping that entry is harmless. Without uv, run the same
commands in a virtual environment after `python -m pip install "pytest-selective==$VERSION"`. When pytest settings
change later, the planner falls back to every lane until someone reviews and refreshes the fingerprints.

### Prove the config locally

On a throwaway branch made from the adoption branch, after committing the lane config, commit one probe edit at a
time and plan it against its parent:

```bash
uv run --refresh-package pytest-selective --no-project --with "pytest-selective==$VERSION" \
  python -m pytest_selective.ci --config .github/test-lanes.json --base HEAD^ --head HEAD
```

Do not plan against `origin/DEFAULT` before the merge: DEFAULT lacks `.github/test-lanes.json`, a global input, so
every probe would report `global input: .github/test-lanes.json` and select every lane. The parent commit already has
the config, so the plan sees only the probe edit.

Expected: JSON with `lanes` (one boolean per lane), `reason` and `lane_reasons`. A README edit gives every lane
`false` (or only `package`, when the build embeds the README) with `no affected tests or changed inputs`; a source
edit selects the lanes of the tests that import it (`affected test: tests/test_x.py`); a lockfile or workflow edit
selects every lane (`global input: ...`). Probe a prose-only file that no lane covers (a docs page; without a `docs/`
directory, a CHANGELOG, RELEASING or CONTRIBUTING file, or the README unless the package lane embeds it), each
requirements file, a source module, a test, a benchmark, a nested file in each directory you narrowed, and each
workflow. If a source edit selects every lane
(`all graph test files affected`), every test reaches it, often through a package `__init__.py`: correct, not a misroute.

## 4. Wire the workflows

### 4.1 The planner job

Add to each workflow that runs lane jobs. The snippets in this file write third-party actions as `@vN`; use the
repository's own ref for each one instead (its SHA and `# vX.Y.Z` comment, when it pins SHAs):

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
        uses: gigaverse-app/pytest-selective/actions/plan-lanes@v1   # or step 1's SHA pin
        with:
          config: .github/test-lanes.json
```

`full` defaults to `auto`: pull requests and pushes select; `workflow_dispatch`, `workflow_call`, `schedule` and
`release` events, and pull requests labelled `test:full`, run every lane. Reruns keep the first attempt's selection.
Keep (or propose) a scheduled full run, and make sure each workflow with lane jobs has `workflow_dispatch:`: it is
how you start a full control in step 8.

The action also uploads its plan as a `test-lane-selection` artifact, which
[CI-esta](https://github.com/gigaverse-app/ci-esta) renders. Give each planner job in one workflow run its own
`artifact-name`, or set `artifact-name: ''` to skip the upload; the plan and the `lanes` output stay the same.

### 4.2 Gate each lane job

```yaml
  tests:
    needs: select-tests
    if: >-
      ${{ always() && !cancelled() && (needs.select-tests.result != 'success' ||
          fromJSON(needs.select-tests.outputs.lanes).tests) }}
```

A skipped matrix job is listed under its unevaluated name (for example `${{ matrix.name || matrix.python }}`),
because the matrix never expands. Mention it in the report, or give the job a name that also reads well unexpanded,
such as `name: tests (${{ matrix.python }})`.

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
- **Probe branches before the merge.** With branch pushes kept, each probe branch's first push (step 7) plans
  against DEFAULT, which does not have your workflow change yet, so it runs every lane. That full run is not a
  misroute and costs a matrix per probe. Make it useful or stop it: the docs-only probe's push runs are a full
  control at the probe head (step 8), so keep them; cancel the source probe's push runs as soon as they start
  (`gh run cancel RUN --repo "$REPO"`) and judge that probe by its `pull_request` runs. The cost ends once the
  adoption merges.
- **`paths:` and `paths-ignore:` filters.** Remove them from every workflow that gets a gate; the lanes replace
  them. A required gate in a workflow that a filter skipped never reports, so a docs-only pull request would wait on
  it forever. This is a behavior change: a change the filter skipped (say `docs/**`) now starts the planner, the
  unconditional jobs and the gate. Say so in the report, with its cost (step 10, net effect).
- **`branches:` filters.** A probe pull request opened against your adoption branch does not start workflows filtered
  to `pull_request: branches: [main]`. Prove those workflows with routing tests and local plans, and say in the report
  that their hosted probe waits for the merge.

### 4.4 Jobs on a publish path

One rule: a job that a publish or deploy job `needs:`, directly or transitively, is never skipped, because a skipped
job skips its dependents and so the publication. Leave it ungated, as it is. If it is expensive and you want pull
requests to skip that work, admit its steps instead of the job: the job always runs and succeeds, so its dependents
still run, and only the expensive steps skip. Plan inside the job and let a failed plan run everything:

```yaml
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0
          persist-credentials: false
      - id: plan
        continue-on-error: true          # a failed plan runs the steps below
        uses: gigaverse-app/pytest-selective/actions/plan-lanes@v1
        with:
          config: .github/test-lanes.json
          artifact-name: ''
      - if: ${{ steps.plan.outcome != 'success' || fromJSON(steps.plan.outputs.lanes).package }}
        run: python -m build && python -m twine check --strict dist/*
```

Keep the steps that produce what the publish job downloads unconditional. Every other job that installs, builds or
tests is gated as in 4.2.

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
      - uses: gigaverse-app/pytest-selective/actions/validation-gate@v1
        with:
          needs: ${{ toJSON(needs) }}
          lanes: ${{ needs.select-tests.outputs.lanes || '{}' }}
          lane-jobs: '{"tests":["tests"],"bench":["bench"],"package":["package"],"routing":["routing"]}'
```

It passes only when every prerequisite succeeded, or was skipped while the planner succeeded and every lane mapped to
that job is `false`. A failed, cancelled or skipped planner, a failed job, or a skip of an unmapped job fails it. It
installs nothing. If the repository already has an aggregate job, keep its job id and name and replace its logic with
this step; the routing test's `GATE` names that id (step 6).

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
      - run: python -m pip install "pytest-selective>=VERSION,<2"   # brings pytest and PyYAML; ==VERSION with SHA pins
      - run: python -m pytest ci_tests -q
```

- Keep `pytest-selective` out of the main test matrix and its requirements. Make sure the main test command does not
  collect `ci_tests/` (`testpaths`, or `--ignore=ci_tests`).
- If mypy or pyright checks every directory, exclude `ci_tests/` or give it its own check. Adding `pytest-selective`
  to a type-check requirements file makes that file an environment input (`*requirements*.txt`), so its next bump
  would run every lane; list it in `graph.global_inputs` only if tests really use it.
- pre-commit and prek only check tracked files: `git add` new files before running the hooks.

Start from this file, `ci_tests/test_ci_routing.py`. Adapt the rows, `WORKFLOW` and `GATE`; the fixture copies
every tracked file, so a misroute cannot hide behind a file the test forgot to copy:

```python
"""Route real Git changes through the committed lane config (pytest-selective)."""

from __future__ import annotations

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
# <the repo's test workflow>: tests.yaml, ci.yml, ...
WORKFLOW = ROOT / ".github/workflows/test.yml"
PLANNER = "select-tests"
# The gate job's id. Keep an existing aggregate job's id, for example "success".
GATE = "gate"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path) -> str:
    git(repo, "add", "-A")
    identity = ["-c", "user.name=routing", "-c", "user.email=routing@example.com", "-c", "commit.gpgsign=false"]
    git(repo, *identity, "commit", "--quiet", "--no-verify", "--allow-empty", "--message", "routing probe")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A copy of every tracked file, so no file the planner reads can be missing from the fixture."""
    git(tmp_path, "init", "--quiet")
    for path in git(ROOT, "ls-files", "-z").split("\0"):
        source, target = ROOT / path, tmp_path / path
        # Skips the empty tail, submodules and files deleted in the working tree.
        if path and (source.is_symlink() or source.is_file()):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target, follow_symlinks=False)
    return tmp_path


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", {**NONE, "package": True}),
        # Prose no lane covers; without docs/, use CHANGELOG.md or RELEASING.md.
        ("docs/index.md", NONE),
        # Requirements the tests do not install, narrowed out of graph.global_inputs.
        ("docs/requirements.txt", NONE),
        ("requirements-mypy.txt", NONE),
        ("tests/test_other.py", {**NONE, "tests": True}),
        ("src/toy/other.py", {**NONE, "tests": True, "package": True}),
        # Non-Python sources the tests exercise (a C extension, stubs), declared as lane inputs.
        ("src/toy/_speedups.c", {**NONE, "tests": True, "package": True}),
        ("tests/benchmarks/test_bench.py", {**NONE, "tests": True, "bench": True}),
        ("tox.ini", EVERY),
        (".github/test-lanes.json", EVERY),
        (".github/workflows/test.yml", EVERY),
    ],
)
def test_a_change_runs_exactly_its_lanes(repo: Path, path: str, expected: dict[str, bool]) -> None:
    base = commit(repo)
    with (repo / path).open("a", encoding="utf-8") as handle:
        handle.write("\n# routing probe\n")
    result = plan(repo, CONFIG, base, commit(repo))
    assert result.lanes == expected, result.lane_reasons


def test_missing_history_and_full_checkpoints_run_every_lane(repo: Path) -> None:
    head = commit(repo)
    # No previous commit, as on a new branch's first push.
    assert plan(repo, CONFIG, "0" * 40, head).lanes == EVERY
    assert plan(repo, CONFIG, head, head, full=True).lanes == EVERY


def test_the_gate_guards_every_job_and_lane_jobs_run_when_planning_fails() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the `on:` key as the boolean True.
    assert "pull_request" in workflow[True]
    jobs = workflow["jobs"]
    (step,) = [step for step in jobs[GATE]["steps"] if "validation-gate" in step.get("uses", "")]
    lane_jobs = json.loads(step["with"]["lane-jobs"])
    assert set(jobs[GATE]["needs"]) == set(jobs) - {GATE}
    assert {lane for lanes in lane_jobs.values() for lane in lanes} <= set(CONFIG.lanes)
    gated = {name for name, job in jobs.items() if f"needs.{PLANNER}.outputs.lanes" in str(job.get("if", ""))}
    # Every job that a lane admits is in the gate's lane map, and nothing else is.
    assert set(lane_jobs) == gated
    for job, lanes in lane_jobs.items():
        condition = " ".join(jobs[job]["if"].split())
        assert "always() && !cancelled()" in condition, job
        assert f"needs.{PLANNER}.result != 'success'" in condition, job
        assert all(f"fromJSON(needs.{PLANNER}.outputs.lanes).{lane}" in condition for lane in lanes), job
```

Add a row for every directory you narrowed, every requirements file, each non-Python source input, each workflow and
each lane, using real tracked paths. A row only names its path; it does not make this test depend on that file. A row appends a comment; a `<workflow>#<job>` input ignores comments, so edit the job itself in that row. With
several workflows, repeat the gate test per workflow with its own `GATE`. Make the file pass the repository's own
linters, formatter and type checker before committing: for example, ruff's `required-imports` may demand
`from __future__ import annotations` (the template has it), and black or `ruff format` with a shorter line length
reflows it. Run it locally with `uv run --refresh-package pytest-selective --no-project --with "pytest-selective==$VERSION" pytest ci_tests -q` and
commit it.

## 7. Prove it on hosted CI

1. Push the branch and open the draft pull request. Its first run changes workflows, so every lane runs: that is the
   full baseline, not a misroute.
2. Branch from the adoption branch, edit only prose no lane covers (a docs page and a README line; without a `docs/`
   directory, a CHANGELOG or RELEASING line), push, and open a probe pull request against the adoption branch (mind
   4.3's `branches:` filters, and its note on the probe's own push runs). List what the pull request executed:

   ```bash
   gh run list --repo "$REPO" --branch PROBE_BRANCH --event pull_request --json databaseId,workflowName,conclusion
   gh run view RUN --repo "$REPO" --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
   ```

   Expected: the planner, lint, docs, the `package` lane only if the build embeds the README, the jobs a publish job
   needs (4.4), and the gate ran; every other lane job is `skipped`; the gate succeeded. Any other job that installs,
   builds or tests and still ran is a missed gate: gate it as in 4.2.
3. Repeat with a one-line source change: its lanes run in full, the rest skip.
4. Keep the probe pull requests open until you have measured, then close them without merging and delete their
   branches.

## 8. Measure

Compare a selected run with a full control **at the same head**:

- Selected: the docs-only probe's `pull_request` runs.
- Full control: if the probe branch's push runs already ran every lane at the probe head (4.3), use them. Otherwise
  dispatch every workflow the selected side ran, on the probe branch; `workflow_dispatch` plans a full checkpoint, so
  every lane runs:

  ```bash
  gh workflow run WORKFLOW --repo "$REPO" --ref PROBE_BRANCH      # once per workflow
  ```

  Dispatch only the workflows this adoption gates. A workflow without `workflow_dispatch:` returns HTTP 422
  (`Workflow does not have 'workflow_dispatch' trigger`); do not add the trigger to workflows you otherwise leave
  alone. Leave such workflows out of both sides and say the comparison covers only the gated workflows. GitHub
  dispatches only workflows whose file exists on DEFAULT, and may read the trigger from DEFAULT's copy rather than the
  branch's: if a workflow gains `workflow_dispatch:` only in your adoption and the dispatch is refused, measure after
  the merge. A rerun is
  not a control: it keeps the selection. Do not wait on a `test:full` label; creating one is the human's step 9.

Both sides then share a head SHA: a `pull_request` run records the branch head as its `head_sha`, although it checks
out the merge commit, and a dispatch or push run on the branch records the same commit. Record both checked-out SHAs.

```bash
gh run list --repo "$REPO" --commit HEAD_SHA --json databaseId,workflowName,event,conclusion,createdAt
uv run --no-project https://raw.githubusercontent.com/gigaverse-app/pytest-selective/v1/scripts/measure_ci_runs.py \
  "$REPO" --selected RUN_A RUN_B --full RUN_C RUN_D --output .test-impact/comparison.json
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
- Create the `test:full` label, if it does not exist: adding it to a pull request and then closing and reopening the
  pull request runs every lane (adding a label alone starts nothing unless a workflow lists `labeled`).
- Approve any trigger change from 4.3 and a scheduled full run.
- Merge. Then a docs-only pull request against the default branch proves the workflows that 4.3's filters hid.

## 10. Report

Use this in the pull request body, filled in:

```markdown
## pytest-selective adoption

pytest-selective vX.Y.Z: actions at `@v1` (or `@<sha> # vX.Y.Z` where tags are rejected), routing tests install
`pytest-selective>=X.Y.Z,<2`.

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
Workflows compared: ... (and any left out, such as one without `workflow_dispatch:`).

### Net effect
- Docs-only pull requests: before ... runner-seconds (0 where a removed `paths-ignore` skipped them), after ....
- Code changes: lane jobs now wait for the planner, about N s.
- Changes that now skip tests: ... (prose and tooling the old filters did not cover).

### Trigger changes (behavior change)
- Removed `paths-ignore: [...]` from `<the repo's test workflow>`; added `workflow_dispatch:` ... (or "none").

### Evidence
- N routing tests: docs, requirements, source, tests, benchmarks, workflows, missing history, full checkpoint.
- Probe pull requests: [docs-only](https://github.com/OWNER/NAME/pull/N), [source](https://github.com/OWNER/NAME/pull/N).

### For you to decide
- Required check: `Test gate` replaces ...
- Label `test:full`; trigger change; scheduled full run.

### Not done or not verified
- Skipped matrix jobs show their unevaluated name (`matrix.name || matrix.python`), if kept.
- ...
```

The net effect and trigger changes are required. Write them honestly: when CI was already cheap, or a `paths-ignore`
already skipped docs, say the adoption saves little, what it costs (planner latency on code changes; docs-only runs
going from 0 to about N runner-seconds), and what it buys (a gate that can be required, and skips for changes the old
filters missed).

For depth: [configuration reference](https://pytest-selective.readthedocs.io/en/latest/docs/configuration/),
[CI guide](https://pytest-selective.readthedocs.io/en/latest/docs/ci/),
[documentation-only audit](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/skip-unrelated-ci/),
[declaring non-Python inputs](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/sidecar-dependencies/),
[guarantees and limits](https://pytest-selective.readthedocs.io/en/latest/docs/evidence/).
