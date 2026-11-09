# Plan once, execute across compatibility lanes

Use `pytest-selective execute-plan` to run a file plan emitted by the public
test-impact action. Every matrix job consumes the same plan; it does not need
Git history or a second dependency analysis.

```yaml
- run: uv run --locked pytest-selective execute-plan -- -q -n 4 --dist=worksteal
  env:
    CI_PLANNER_RESULT: ${{ needs.plan.result }}
    CI_TEST_MODE: ${{ needs.plan.outputs.mode }}
    CI_TEST_FILES: ${{ needs.plan.outputs.files }}
    CI_COVERAGE: 'true'
```

`files` must be the action's `test_roots_json` output. A successful `none` plan
does not start pytest. Failed planning, malformed JSON, unknown modes or an
empty scoped selection execute the complete roots. Roots default to `tests`;
override with `--full-roots tests/unit tests/integration -- ...`. Paths with
spaces remain single arguments, and pytest receives its normal exit status.

`CI_COVERAGE=true` adds `--cov --cov-report=term-missing --cov-report=xml` only
for full execution. The environment must have pytest-cov installed. Keep
coverage thresholds in your project configuration; do not enforce a full-suite
threshold on selected files. The outer execution disables the selective plugin
because planning already happened. Integration tests can still load it explicitly.

When lane and file selection share a graph, derive the file config:

```sh
pytest-selective file-config --lanes .github/test-lanes.json --output /tmp/test-impact.json
```

This combines the graph's global inputs with the lane config's explicit global
inputs. Declare `global_inputs` before using it. Lane-specific `inputs` remain
lane admission rules; they do not automatically make every test file affected.
Declare non-import dependencies in the graph as usual.

pytest-selective's own CI uses four work-stealing workers on each existing
runner. Its full checkpoints retain all Python 3.11 and 3.14 compatibility tests
on Linux, Windows and macOS. Coverage runs on Python 3.14 on all three systems,
avoiding a second instrumentation pass on Python 3.11. The minimum-pytest lane,
Quint contract and installed-distribution smoke remain independent checks.

<!-- Documentation-only selection measurement; no execution inputs change. -->
