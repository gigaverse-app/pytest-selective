# Adoption recipe

Use Python 3.11+ and Git 2.24+. The planner interpreter must understand the
target's syntax; it can be separate from the application environment. Install
pytest-selective from PyPI using the project's dependency workflow. Keep the
resolved version in its lockfile; use a source revision only for unreleased work.

## Try native pytest first for local edits

```bash
uv add --dev pytest-selective
uv run pytest --selective
uv run pytest --selective --selective-base origin/main
uv run pytest --no-selective
```

Preserve the normal test paths and flags. Native mode collects normally; use the
[pre-collection runner](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/local-development.md#pre-collection-runner)
when application imports dominate. CI and advanced dependencies use the reviewed
configuration below.

## Start with the actual layout

For a typical `src/` project, a file-selection config is:

```json
{"module_roots": ["src", "."], "test_roots": ["tests"]}
```

Save as `.github/test-impact.json`, adapting both roots. Review pytest settings,
collection hooks and plugins, then run:

```bash
pytest-selective fingerprints --config .github/test-impact.json \
  --head HEAD --output pytest-fingerprints.json
```

Copy the returned object into the config's `pytest_policy` field after reviewing
the collection contract. Do not blindly accept a new fingerprint to silence an
unexpected fallback. Add non-Python dependencies using the
[configuration guide](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/configuration.md).

```bash
pytest-selective affected --config .github/test-impact.json \
  --base origin/main --head HEAD --output selection.json \
  --explanation-output explanation.json
```

Inspect the exit code before reading output. The CLI's operational failure (exit
1) requires the full suite; declaration errors (exit 2) need repair. On success,
`full` runs complete roots, `scoped` runs `selected` as an argument list, and
`none` skips pytest. Preserve existing pytest flags and filters. See the
[runner integration](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md)
for the shell/JSON boundary and Actions fallback behavior.

## Prefer complete lanes when evidence requires them

Wrap the graph config under `graph` and add `lanes` in a separate lane config:

```json
{
  "graph": {"module_roots": ["src", "."], "test_roots": ["tests"]},
  "global_inputs": [
    "pyproject.toml", "uv.lock", ".github/test-lanes.json",
    ".github/workflows/ci.yml", "actions/**"
  ],
  "lanes": {
    "unit": {"roots": ["tests/unit"]},
    "integration": {"roots": ["tests/integration"], "inputs": ["schemas/**"]}
  }
}
```

This is a starting shape, not a complete inventory for an arbitrary repository.
Populate `graph.pytest_policy` from the reviewed fingerprints. Adapt locks,
workflows, roots and explicit inputs to files the target actually uses; map every
test root to a job that executes it. Validate with:

```bash
python -m pytest_selective.ci --repo . --config .github/test-lanes.json \
  --base origin/main --head HEAD
```

For Actions, use `plan-lanes` with full history and expose its `lanes` job output.
An admitted job runs when its lane is true **or planning failed**. Explicit manual/release runs,
schedules and a full-test override request `full: true`; ordinary main pushes
use the changed base/head trees so docs-only merges also execute zero tests. Start from the
[complete lane guide](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/ci.md#select-whole-ci-lanes),
not an invented action input. The repository's
[routing tests](https://github.com/gigaverse-app/pytest-selective/blob/main/tests/test_repository_ci.py)
show real-Git positive/negative controls; adapt the scenarios to the consumer.

## Measure

On GitHub Actions, the read-only
[timing exporter](https://github.com/gigaverse-app/pytest-selective/blob/main/scripts/measure_ci_runs.py)
requires authenticated `gh` and completed successful attempts with matching heads:

```bash
python scripts/measure_ci_runs.py OWNER/REPO SELECTED_RUN_ID FULL_RUN_ID \
  --output comparison.json
```

Run this from a pytest-selective checkout, substituting the repository and run
IDs. Verify the checked-out merge identity separately in checkout logs. On other
runners, collect equivalent timestamps instead of implying GitHub APIs exist.
Include setup/cleanup and planner overhead; report elapsed separately from the
sum of parallel job durations. Keep unrelated reporter jobs explicit.
