# pytest-selective

Run the Python test files affected by a Git change, and explain why they were selected.

Extracted from the dependency-graph selector used by Gigaverse's backend, AI,
and shared Python infrastructure. Planning reads immutable Git objects; it does
not import your application, collect tests, or start its services.

The planner requires Python 3.11+ and Git 2.24+. Use a planner Python version
at least as new as your source syntax. The CI action uses Python 3.14. Your tests may run with a different Python version.

## Install and select

~~~sh
pip install "pytest-selective @ git+https://github.com/gigaverse-app/pytest-selective.git"
pytest-selective affected --config .github/test-impact.json --base origin/main --head HEAD --output selection.json
~~~

Commit a configuration for your repository:

~~~json
{
  "module_roots": ["src", "."],
  "test_roots": ["tests"]
}
~~~

The JSON report contains selected test file paths, mode (scoped, full, or none),
and selection reasons. Use a subprocess argument list to pass selected paths to
pytest; an empty selection must skip pytest, since pytest with no paths runs
the whole suite. Planning analyzes committed revisions, not working-tree edits.

## What it preserves

- Transitive imports, package initialization, ancestor conftests, and configured startup modules.
- The union of base and head dependencies, including deleted and renamed files.
- Reader-owned non-Python inputs through comments and YAML sidecars.
- Cached parsing and graphs, optional runtime file-read auditing, selection explanations,
  startup-floor diagnostics, and duration-based shard planning.
- Conservative full-suite fallback when a narrower selection cannot be established.
  Invalid dependency declarations produce an actionable error.

Static analysis cannot discover every dynamic import, plugin registration, or file read.
Declare those dependencies and retain full-suite checkpoints. Selection determines
which tests are affected; your existing markers and CI policy determine which may run.

## GitHub Actions

Use gigaverse-app/pytest-selective/.github/actions/test-impact@<commit> with
config, base, and full-roots. The action falls back to all configured roots
on operational planning failures. It reports malformed declarations as errors.
Full history is recommended (actions/checkout with fetch-depth: 0).

## Audit and explanation

~~~sh
pytest-selective affected --config .github/test-impact.json --base origin/main --explanation-output explanation.json
pytest -p pytest_selective.impact_audit_plugin --impact-audit-dir impact-audit
pytest-selective audit --config .github/test-impact.json --records impact-audit
~~~

Install the audit extra to use the pytest recorder.

## Development

~~~sh
uv sync
uv run pytest
uv run ruff check .
uv build
~~~

See [provenance](PROVENANCE.md) for the extraction boundary and original ownership.
See [lessons from pytest-impacted](docs/pytest-impacted.md) for subsequent improvements.

## Select whole CI lanes

For tests that must produce complete conformance evidence, use
`.github/actions/plan-lanes` or `python -m pytest_selective.ci` with a config:

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

The action returns a `lanes` JSON object. Expose it as a planning-job output,
then gate each expensive job with `always() && !cancelled()` and either a true
lane value **or a failed planning job**. This preserves tests if planning fails.
Run the action with `full: true` on main, schedules, and full-test overrides.
Selected jobs retain all of their existing tests and evidence checks.
