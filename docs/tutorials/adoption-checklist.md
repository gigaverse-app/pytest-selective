---
title: Get the most benefit from pytest-selective
description: A staged adoption tutorial and checklist for local pytest, pre-collection planning, CI lanes, dependency audits, hygiene, timing feedback and measured rollout.
---

# Get the most benefit from pytest-selective

Choose the level that avoids your actual cost. The native plugin avoids
unaffected test execution. The pre-collection runner also avoids importing and
collecting unrelated files. Whole-lane CI planning can avoid starting runners,
services and application installation altogether.

Use this checklist in your adoption PR. Mark each stage **verified**, **deferred**
or **not applicable**, with a reason. Pair it with the
[CI-esta adoption checklist](https://github.com/gigaverse-app/ci-esta/blob/6a694957568c81929a2b3021064ad9674516fb7b/docs/tutorials/adoption-checklist.md)
for reporting, setup, sharding, history, evidence reuse and security integration.
Selection remains opt-in; installing the package alone does not narrow pytest.

## 1. Run the disposable example

Use Python 3.11+ and Git 2.24+. Plan with an interpreter at least as new as your
source syntax; the planner need not install your application dependencies.

```bash
git clone https://github.com/gigaverse-app/pytest-selective.git
cd pytest-selective
uv sync --locked
uv run python scripts/tutorial.py --output tutorial-report.json
```

- [ ] The transitive regression selects its reader and catches the introduced failure.
- [ ] An unrelated README selects no tests and does not launch pytest accidentally.
- [ ] A shared conftest change retains the full configured inventory.
- [ ] The tutorial exits successfully despite its intentionally failing pytest controls.

**Done when:** you understand the difference between `scoped`, `none` and `full`
plans. This demonstrates behavior, not a wall-time speedup. The script uses a
temporary Git repository; it does not alter your project or staging area.

## 2. Choose local collection or pre-collection execution

In your application repository, install the selector in the test environment:

```bash
uv add --dev pytest-selective
uv run pytest --selective
uv run pytest --no-selective
```

Commit the dependency and lockfile change through your normal workflow before
trying a narrow source edit. Uncommitted environment changes intentionally
select everything and would hide the benefit you are trying to verify.

The plugin collects normally and then deselects. Its default includes staged,
unstaged and nonignored untracked edits relative to HEAD. An explicit
`--selective-base origin/main` also includes changes since that exact ref.
Keep normal test paths, marker filters, fixtures and assertion plugins.

If collection or startup is expensive, create `.github/test-impact.json`:

```json
{
  "module_roots": ["src", "."],
  "test_roots": ["tests"]
}
```

Review and record [collection-policy fingerprints](../configuration.md#review-and-record-collection-policy)
before relying on selection in a repository with pytest configuration. Then use:

```bash
uv run pytest-selective run --config .github/test-impact.json -- -q
uv run pytest-selective run --config .github/test-impact.json --full -- -q
```

- [ ] Inventory every intended test root and any custom filename/collection policy.
- [ ] Check both local edits and committed base/head changes.
- [ ] Use the native plugin for custom collection/node-oriented workflows unless
  you have verified that pre-collection file planning models them correctly.
- [ ] Keep explicit full execution for whole-suite coverage and conformance requirements.
- [ ] Do not enable selection globally while validating adoption.

**Done when:** an actual small source edit runs the intended tests, while a full
control still passes. **Rollback:** `--no-selective` for the plugin or `run --full`
for the runner. Remove a global selective setting if your project previously added one.

## 3. Declare dependencies that Python imports cannot reveal

Follow the [reader-owned sidecar tutorial](sidecar-dependencies.md). For example,
place this beside the test that reads the fixture, as `test_prices.py.gv-dependency.yaml`:

```yaml
dependencies:
  - inputs: ["//tests/data/prices.json"]
    kind: content
    reason: The test reads expected prices from this JSON fixture.
```

- [ ] Declare templates, fixtures, schema files, AST/text scans and subprocess helpers.
- [ ] Use `content` for bytes read as data, and `import` when the reader executes
  Python and needs that module's transitive dependencies.
- [ ] Keep declarations beside readers; use central rules for actual shared policy.
- [ ] Review locks, environment configuration, external checkout pins and plugin startup.
- [ ] Retain default global inputs until a narrower environment contract is verified.
- [ ] Review nested/custom pytest configuration before refreshing fingerprints.
- [ ] Repair unmatched paths, invalid sidecars and duplicate keys; do not suppress them.

Inspect the plan before executing it:

```bash
uv run pytest-selective affected --config .github/test-impact.json \
  --base origin/main --working-tree --output selection.json \
  --explanation-output explanation.json
uv run pytest-selective explain --config .github/test-impact.json \
  --test tests/test_prices.py --source src/shop/prices.py
```

Adapt the test/source paths. **Done when:** real edits to each declared input
select its readers, and an unrelated file does not broaden the plan. Deleted
inputs and both sides of a rename belong in your controls.

## 4. Move CI selection ahead of expensive setup

Use the [complete CI recipe](../ci.md), or the
[whole-lane tutorial](skip-unrelated-ci.md) when a suite must run intact.

| Interface | Choose it when | Override / contract |
| --- | --- | --- |
| `gigaverse-app/pytest-selective@v1` | Plan ordinary pytest files before collection | Root convenience entry point; same implementation as `actions/test-impact` |
| `actions/test-impact@v1` | Use the direct action, including runners without root self-reference support | Shared `full: auto` checkpoints; consume `mode` and `test_roots_json` without reparsing reports |
| `actions/plan-lanes@v1` | Skip complete unaffected jobs while preserving coverage/conformance | Shared `full: auto` checkpoints; `lanes` is a boolean JSON map |
| `actions/pytest-expansion@v1` | Reject unexplained global conftest expansion before application setup | Configure roots/prefixes to your project; this does not itself run tests |

Specialized action paths above are relative to `gigaverse-app/pytest-selective/`.
See every input and output in the [action reference](../actions.md). Python
package versions, the moving Actions major and installed skills update separately.

- [ ] Collect a complete change set with enough Git history before selecting.
- [ ] Model lane execution inputs, including called actions/reusable workflows.
- [ ] Avoid broad `.github/**` globals when only execution workflows affect tests.
- [ ] Consume one successful plan consistently across matrix workers; do not run
  a second hidden selector against an already selected exact-file manifest.
- [ ] Keep services, coverage and evidence validators intact inside admitted lanes.
- [ ] Do not invoke bare pytest on a `none` plan; it runs the whole suite.
- [ ] Missing history/operational uncertainty runs the full configured roots.
  Invalid declarations remain visible failures to repair.
- [ ] Make the planner required and validate skips through an aggregate gate.
- [ ] Keep ordinary PRs and main pushes selective, with explicit full/manual and
  scheduled checkpoints. Verify label-trigger behavior instead of assuming it.

**Done when:** the acceptance matrix below passes using actual commits and the
real workflow. A local plan alone does not establish which hosted jobs execute.

| Control | Expected result |
| --- | --- |
| Unreferenced README or PR-template change | Zero tests, including routing, tutorial and installed-package smoke lanes unless they declare that document as an input; metadata/docs checks may still run |
| Source or transitive helper | All affected reader tests or complete lanes run |
| Fixture, sidecar, subprocess entry point | Declared readers run |
| Shared conftest, lock, collection policy or execution workflow | Required broad/full work runs or the policy fails visibly for review |
| Deleted input / renamed module | Dependents from both Git trees remain covered |
| Missing history | Full execution, with the fallback explained |
| Failed planner / invalid configuration | Cannot yield a green skipped required gate |
| Explicit full override | Complete configured suite and existing validators run |

## 5. Keep the graph narrow and check its blind spots

Run a representative full workload with the optional file-read recorder, then
audit the resulting records:

```bash
uv run pytest --no-selective -p pytest_selective.impact_audit_plugin --impact-audit-dir impact-audit
uv run pytest-selective audit --config .github/test-impact.json --records impact-audit
```

- [ ] Declare missing observed inputs at their reader and repeat the affected route.
- [ ] Keep full checkpoints for paths the recorder has not observed.
- [ ] Use `explain`, `dependencies` and `conftest-impact` to investigate unexpectedly broad selections.
- [ ] Move helpers/fixtures to the narrowest consuming scope before accepting a new startup floor.
- [ ] Review and set `floor_budget`; verify a deliberately excessive floor fails visibly.
- [ ] Add the [expansion and test-file isolation guards](../pytest-hygiene.md)
  where needed; do not hide new global dependencies behind unexplained exceptions.
- [ ] Consider `warm` only after measuring graph construction; cache misses must
  rebuild safely and must never become proof that tests passed.

Use the [selection-health guide](../selection-health.md) for complete commands.
Audits observe executed paths; they cannot prove that every possible runtime
dependency has been declared. Keep intentional external-state checks separate.

## 6. Balance selected work without changing eligibility

Use [CI-esta timing retention](https://github.com/gigaverse-app/ci-esta/blob/main/docs/learned-test-timings.md)
when partial whole-file runs would otherwise erase useful costs. CI-esta owns
the lifecycle; pytest-selective owns inventory and partitioning.

- [ ] Use separate timing histories per environment and fixed marker lane.
- [ ] Validate complete files and all expected reports before learning.
- [ ] Restore once, then freeze the plan or duration input for every worker.
- [ ] Verify that every selected file is assigned exactly once and unknown files remain included.
- [ ] Compare existing xdist with proposed shard/pool layouts including startup and service costs.
- [ ] Keep timing retention, job evidence reuse and test eligibility as separate opt-ins.

Setting `--shard-seconds`, `--max-shards` or a duration manifest changes scheduling
estimates, not the dependency contract. A case-filtered local run may be valid for
the plugin while still being unsuitable as a complete-file timing observation.

## 7. Know which commands and scripts to use

| Surface | Purpose / boundary |
| --- | --- |
| `pytest --selective`, `--no-selective`; `pytest-selective run` | Local execution, including uncommitted changes; choose collection behavior explicitly. |
| `affected`, `explain`, `dependencies`, `conftest-impact` | Plan and inspect dependency routes; preserve structured explanations for review. |
| `fingerprints`, `floor-budget`, `audit`, `warm` | Collection-policy review, breadth budgets, observed-read checks and cache preparation. A fingerprint refresh is a review step, not an automatic fix for every fallback. |
| `typecheck-scope` | Scope type checking with its own checker/global-input contract; retain a full fallback. Inspect `pytest-selective typecheck-scope --help` and the [scope implementation](../../src/pytest_selective/typecheck_scope.py). |
| `python -m pytest_selective.ci` | Whole-lane planning outside the GitHub action; the [CI recipe](../ci.md) documents its JSON and full override. There is no `pytest-selective lanes` command. |
| `pytest-selective-expansion` | Standalone expansion guard; use the [hygiene recipe](../pytest-hygiene.md). |
| [scripts/tutorial.py](../../scripts/tutorial.py) | Executable Git/selection/pytest example used in stage 1. |
| [scripts/benchmark_graph.py](../../scripts/benchmark_graph.py) | Compare cold, warm and incremental graph construction on fixed revisions. Its in-memory fingerprint refresh is for measurement, not adoption approval. |
| [scripts/benchmark_parsing.py](../../scripts/benchmark_parsing.py), [benchmark_rust.py](../../scripts/benchmark_rust.py) | Maintainer parser experiments; they do not enable a production alternate parser or establish hosted savings. |
| [scripts/compare_impacted.py](../../scripts/compare_impacted.py) | Optional comparison experiment; needs a separately installed pytest-impacted revision. Not a runtime dependency. |
| [scripts/measure_ci_runs.py](../../scripts/measure_ci_runs.py) | Compare recorded GitHub runs with explicit identities; inspect `--help` and the [measurement limits](../evidence.md). |
| [scripts/ci_file_config.py](../../scripts/ci_file_config.py), [run_ci_tests.py](../../scripts/run_ci_tests.py) | This toolkit's CI adapters; consumers normally use the public action/runner, not copied wrappers. |
| [scripts/public_actions.py](../../scripts/public_actions.py), [check_docs.py](../../scripts/check_docs.py), [check_metadata.py](../../scripts/check_metadata.py), [smoke_distribution.py](../../scripts/smoke_distribution.py), [render_brand.py](../../scripts/render_brand.py); `documentation/*.py` | Toolkit generation, documentation and release validation. These are maintainer tools, not extra adopter jobs. |

The Python graph/configuration models, inventory, sharding and hygiene helpers
are available for integrations, but reuse the public runner/actions for ordinary
adoption. Do not copy selection logic or create a second dependency declaration
format in an application helper.

## 8. Measure and hand over an adoption that stays useful

- [ ] Compare successful full and selected runs on the same source head and tested
  checkout, with unchanged environment and required checks.
- [ ] Record planning, collection, installation, services, artifacts and reporting
  alongside pytest execution. Fewer files does not by itself mean lower latency.
- [ ] Retain run/attempt IDs, elapsed seconds and summed runner-seconds; repeat
  before claiming an average. Keep cancelled experiments visible separately.
- [ ] Record configuration assumptions, full-run override, rollback and ownership.
- [ ] Route the adoption regression tests through their declared real inputs.
- [ ] Link these results from the PR and update your installed
  [agent skill](../../skills/pytest-selective/SKILL.md) separately from package/action pins.

Use [CI-esta's measurement recipe](https://github.com/gigaverse-app/ci-esta/blob/main/docs/measured-impact.md)
to report the result. Installing a newer selector does not automatically configure
lane routing, runtime audits, hygiene policies, timing retention or evidence reuse.
