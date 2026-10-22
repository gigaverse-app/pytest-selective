# pytest-selective

**Run affected Python tests. See why they matter.**

[![CI](https://github.com/gigaverse-app/pytest-selective/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/gigaverse-app/pytest-selective/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://github.com/gigaverse-app/pytest-selective/blob/main/pyproject.toml)
[![Alpha](https://img.shields.io/badge/status-alpha-E9A23B)](https://github.com/gigaverse-app/pytest-selective/blob/main/CHANGELOG.md)
[![Typed](https://img.shields.io/badge/typing-py.typed-3776AB)](https://github.com/gigaverse-app/pytest-selective/blob/main/src/pytest_selective/py.typed)
[![Ruff](https://img.shields.io/badge/code%20style-Ruff-D7FF64?logo=ruff&logoColor=black)](https://github.com/gigaverse-app/pytest-selective/blob/main/.pre-commit-config.yaml)
[![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/gigaverse-app/pytest-selective/blob/main/LICENSE)

pytest-selective is a **Python test impact analysis** tool for incremental testing
with pytest. It follows dependencies through both sides of a Git change, selects
the affected test files, and explains the result. Plan before collecting tests,
importing your application, or starting databases and workers.

Built from the selector used in Gigaverse's backend, AI, and shared Python
infrastructure. **Alpha:** the API may change before 1.0.
[Provenance and extraction scope](https://github.com/gigaverse-app/pytest-selective/blob/main/PROVENANCE.md).

[Quick tutorial](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/tutorial.md) ·
[Adoption guide](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/configuration.md) ·
[GitHub Actions](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md) ·
[Evidence and limits](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/evidence.md) ·
[Keep selection narrow](docs/pytest-hygiene.md)

## A small change should have an explainable test plan

```text
shop/prices.py changed
    └── shop/checkout.py imports prices
            └── tests/test_checkout.py       RUN
                tests/test_health.py         unaffected
                tests/test_labels.py         unaffected

Shared conftest changed?                     RUN ALL THREE
Only the unreferenced README changed?        SKIP PYTEST
```

The [executable tutorial](https://github.com/gigaverse-app/pytest-selective/blob/main/scripts/tutorial.py)
creates real commits, introduces a pricing regression, and runs pytest on the
selected files. One of three files is selected and catches the regression.
This is a reproducible selection example, **not a wall-time speedup claim**.

## Used by Due and pytest-obligation

[Due](https://github.com/gigaverse-app/due) and
[pytest-obligation](https://github.com/gigaverse-app/pytest-obligation) plan every
pull request with pytest-selective. Their conformance suites need PostgreSQL,
Redis, Celery workers and real framework checkouts, so skipping an unaffected
**lane** saves minutes. Measured on real GitHub Actions runs:

| Change | Full CI | Selective CI | Runner-seconds |
| --- | ---: | ---: | ---: |
| Due: one library test | 6m03s | **3m24s** | 747 → 388 (−48%) |
| pytest-obligation: one MongoDB test | 5m22s | **54s** | 1,602 → 93 (−94%) |
| pytest-obligation: package README | 6m03s | **20s** | 1,691 → 57 (−97%) |

Each row is one successful pair on the same PR head and merge checkout: the
selective run first, then a `test:full` control. Both include planning time.
Single observations, not billed minutes or a promise for every PR. An affected
lane still runs complete, with its conformance evidence checks.

Adoption: [Due #68](https://github.com/gigaverse-app/due/pull/68) and
[pytest-obligation #93](https://github.com/gigaverse-app/pytest-obligation/pull/93),
each with its own lane map (`.github/test-lanes.json`).
[Run links, raw timestamps, method and limits](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22.md),
including Due's widget benchmark, which selection skips entirely.

## Try it in two minutes

Requires **Python 3.11+, Git 2.24+, and uv**. Use a planner Python version at
least as new as your source syntax; the CI action uses Python 3.14. Your test
runtime can use a different Python version when planning runs separately.
The optional audit recorder requires Python 3.11+ in the test environment.

```bash
git clone https://github.com/gigaverse-app/pytest-selective.git
cd pytest-selective
uv sync --locked
uv run python scripts/tutorial.py --output tutorial-report.json
```

```text
transitive regression: scoped, 1/3 files; pytest exit 1 (expected)
documentation only: none, 0/3 files; pytest skipped
shared conftest: full, 3/3 files; pytest exit 1 (expected)
```

The nonzero pytest results are intentional: they prove the selected tests catch
the introduced bug. The tutorial itself succeeds only when all expected outcomes
hold. It uses a temporary repository and leaves your checkout untouched.

## Install in your project

Until the first PyPI release, install from GitHub using Python 3.11+:

```bash
pip install "pytest-selective @ git+https://github.com/gigaverse-app/pytest-selective.git"
```

Pin a reviewed commit in CI. Then follow the
[configuration walkthrough](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/configuration.md)
to declare module roots, test roots, collection-policy fingerprints, and non-Python inputs.

```bash
pytest-selective affected --config .github/test-impact.json \
  --base origin/main --head HEAD --output selection.json \
  --explanation-output explanation.json
```

Planning reads **committed Git trees**. Uncommitted edits are outside the plan.
The report distinguishes `scoped`, `full`, and `none`; an empty selection must
skip pytest, because invoking pytest without paths runs the whole suite.

## Why pytest-selective?

| When your change touches… | The planner accounts for… |
| --- | --- |
| A transitive dependency | Import chains and package initialization |
| A deleted or renamed module | Dependencies in both the base and head trees |
| Fixtures or startup code | Ancestor conftests and configured global modules |
| Templates, schemas, or data files | Reader-owned declarations and YAML sidecars |
| A surprisingly large selection | Dependency paths, startup-floor and blast-radius explanations |
| A large CI suite | Cached parsing, graph reuse, and duration-based shard planning |
| Undeclared runtime reads | An opt-in pytest recorder and audit command |

The CLI emits JSON for your runner. The
[composite action](https://github.com/gigaverse-app/pytest-selective/blob/main/.github/actions/test-impact/action.yml)
adds caching and falls back to complete test roots on operational planning
failures. Invalid dependency declarations fail with a diagnostic that must be fixed.

## What a green run means

Selection is only as complete as the dependency model. Static analysis cannot
discover every dynamic import, plugin registration, environment dependency, or
file read. Declare those edges, audit representative runs, and keep full-suite
checkpoints. A green selected run is not proof that every test would pass.

Selection chooses **which files are affected**; your existing markers and CI
policy still determine which tests may run. Suites that enforce complete
collection or whole-suite coverage need full runs.

For expensive suites that must retain complete conformance evidence, use
[whole-lane selection](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md#select-whole-ci-lanes).
An affected test activates its entire lane, preserving the lane's existing tests
and evidence checks.

[Read the evidence, safety boundaries, and adoption checklist](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/evidence.md).

## Choose the right tool

[pytest-impacted](https://github.com/promptromp/pytest-impacted) offers a pytest-native
`--impacted` workflow, including working-tree changes. pytest-selective focuses on
committed revisions, inspectable JSON plans, runtime dependency audits, and
planning before application startup. Both use static dependency analysis; choose
based on your workflow, and validate selection against your own suite.
See the [lessons from pytest-impacted](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/pytest-impacted.md)
for portability and Git-resolution improvements adopted from that comparison.

## Contribute

```bash
uv sync --locked
uv run pre-commit install
uv run pre-commit run --all-files
uv run pytest -q
uv build
uv run twine check --strict dist/*
uv run python scripts/smoke_distribution.py
```

[Contributing](https://github.com/gigaverse-app/pytest-selective/blob/main/CONTRIBUTING.md) ·
[Documentation](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/README.md) ·
[Release process](https://github.com/gigaverse-app/pytest-selective/blob/main/RELEASING.md) ·
[Report a bug](https://github.com/gigaverse-app/pytest-selective/issues/new?template=bug_report.yml)

---

[![CI measured by CI-esta](https://img.shields.io/badge/CI_measured_by-CI--esta-EA580C)](https://github.com/gigaverse-app/ci-esta)

<sub>[CI-esta](https://github.com/gigaverse-app/ci-esta) reports this repository's
CI timing and renders pytest-selective's selection explanations next to it. It is
optional; pytest-selective does not depend on it.</sub>
