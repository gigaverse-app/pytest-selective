# Evidence, guarantees, and limits

## Reproduce the public demonstration

```bash
uv sync --locked
uv run python scripts/tutorial.py --output tutorial-report.json
uv run pytest -q --cov --cov-report=term-missing --cov-report=xml
```

The tutorial executes the real CLI and pytest in a fresh repository. Its baseline
has three passing test files. Each row compares consecutive commits:

| Change | Complete suite (files) | Selected (files) | Observed outcome |
| --- | ---: | ---: | --- |
| Pricing regression behind a transitive import | 3 | 1 | Selected test fails, detecting the bug |
| Unreferenced README | 3 | 0 | Pytest is skipped; previous regression remains |
| Shared root conftest | 3 | 3 | Full selection still detects the bug |

Fewer selected files is useful only when affected tests remain included. This
example makes no claim about production time saved, recall across arbitrary
projects, or performance against another selector. The script asserts its
expected outcomes and emits commit SHAs and reasons. CI retains the report and
coverage XML under `evidence-<os>-<python>` in each run's artifacts. Both Windows
Python versions retain coverage, including interpreter-specific execution paths.

## What the regression suite exercises

| Contract | Executable evidence |
| --- | --- |
| Transitive imports, deletion, renames, conftests, declaration errors, action fallback | [Graph and CLI tests](../tests/testing/test_impact_graph.py) |
| Human-readable dependency paths and startup-floor analysis | [Explanation tests](../tests/testing/test_impact_explanation.py) |
| Runtime reads and recorder behavior | [Audit tests](../tests/testing/test_impact_audit.py) |
| Optional narrowing of first-party package pin changes | [First-party tests](../tests/testing/test_impact_first_party.py) |
| Name-level narrowing with conservative escape paths | [Name-scope tests](../tests/testing/test_impact_name_scope.py) |
| Duration-aware shard plans | [Sharding tests](../tests/testing/test_pytest_sharding.py) |
| Public install and command workflow | [Tutorial](../scripts/tutorial.py), [distribution smoke checks](../scripts/smoke_distribution.py) |

Consult the current [CI run](https://github.com/gigaverse-app/pytest-selective/actions/workflows/ci.yml)
for results on a particular commit. Test counts and coverage change over time;
the CI badge reports workflow status, not a universal correctness guarantee.

## Safety boundaries

- Plans describe tracked files in committed base and head trees, not local edits.
- Static imports and configured dependencies model reachability. Dynamic plugin
  discovery, external state, environment variables, and undeclared file reads
  may require explicit edges or full-suite policy.
- Runtime audits observe only paths executed during that run. They help find
  missing declarations; they cannot prove all possible dependencies.
- An operational CLI failure exits nonzero. The composite action provides the
  complete-root fallback. A custom runner must implement that handling too.
- Invalid declarations are authoring errors, not permission to skip tests.
- Whole-suite collection proofs, coverage thresholds, and periodic checkpoints
  should use complete suites.

## Adopt with evidence from your project

1. Run selection alongside the full suite without changing its gate.
2. Include real regressions and shared-fixture, deletion, rename, lockfile, and
   non-Python input changes. Investigate any omitted failing test.
3. Compare the same base/head pair. Record selected/total files, cold and warm
   planner time, total CI time, and fallback frequency.
4. Enable selection after validating your declarations and runner behavior.
5. Retain full-suite checkpoints and failure canaries when reusing passing bases.

The [provenance record](../PROVENANCE.md) describes where this code came from.
Its extraction history is not a published performance benchmark.


## Measured consumer CI

See the [2026-10-22 matched CI measurements](benchmarks/2026-10-22.md) for
real Due and pytest-obligation workflow timings, raw job timestamps, preserved
execution contracts and the limits of a single narrow-change comparison.
