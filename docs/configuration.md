# Configure Python test impact analysis

The planner needs Python 3.11+ and Git 2.24+. Use an interpreter at least as new
as your source syntax. It does not need your application dependencies. Your test
runner can use a separate environment.

## Declare the repository layout

Create `.github/test-impact.json`:

```json
{
  "module_roots": ["src", "."],
  "test_roots": ["tests"]
}
```

Paths are repository-relative, with forward slashes. Module roots are directories
containing import packages. Test roots must include every suite you intend to
select. The default filenames are `test_*.py`, `*_test.py`, `*_tests.py`, and
`tests.py`; configure
`test_patterns` for a different collection policy.

## Review and record collection policy

If your repository has `pyproject.toml`, `pytest.ini`, `tox.ini`, or `setup.cfg`,
record its committed pytest-policy fingerprints. Even a discovered configuration
file with no pytest settings can have a fingerprint. This review prevents a new
collection rule from silently invalidating the inventory.

```bash
pytest-selective fingerprints --config .github/test-impact.json \
  --head HEAD --output pytest-fingerprints.json
```

Copy the resulting JSON object into the `pytest_policy` key in your config:

```python
import json
from pathlib import Path

path = Path(".github/test-impact.json")
config = json.loads(path.read_text())
config["pytest_policy"] = json.loads(Path("pytest-fingerprints.json").read_text())
path.write_text(json.dumps(config, indent=2) + "\n")
```

Review custom `python_files`, collection hooks, plugin loading, and test roots
before accepting fingerprints. Commit the config, delete the temporary fingerprint
file, and commit application changes before planning. When collection settings
change, review them and refresh fingerprints against the new committed head.
The CLI reports unreviewed policy as an operational failure; the composite action
runs the complete configured roots.

## Declare inputs that imports cannot describe

Start with the [sidecar tutorial](tutorials/sidecar-dependencies.md) for a runnable
fixture example, directory manifests, dependency comments, and dynamic Python inputs.

For a test that reads a tracked JSON fixture, add a reader-owned comment:

```python
# gv:test-dependency: tests/data/prices.json
```

Or create `tests/test_prices.py.gv-dependency.yaml` beside its owner:

```yaml
dependencies:
  - inputs: ["//tests/data/prices.json"]
    kind: content
    reason: The test reads the expected prices as JSON.
```

Sidecar inputs are relative to the sidecar directory; `//` starts at the repository
root. `content` follows the file's bytes; `import` also follows its dependencies.
The default is `import`. Inputs must match tracked files. Invalid patterns,
missing matches, duplicate YAML keys, and aliases are errors to repair.

Declare lock files, environment manifests, and other suite-wide inputs explicitly:

```json
{
  "readers": ["tests/*.py"],
  "inputs": ["uv.lock", "pyproject.toml"],
  "kind": "content",
  "reason": "All tests use this dependency environment."
}
```

Add that rule to the configuration's `dependencies` array and adapt the reader
patterns to your actual inventory. Central-rule reader patterns use shell-style
matching: here `*` also covers nested paths under `tests/`. Common lockfiles, dependency manifests and pytest configuration already belong
to the default `global_inputs`. Keep those defaults unless you have reviewed a
narrower environment contract; these reader-specific rules are for additional
inputs. Other non-Python files are not automatically global inputs. Use `global_modules` for modules loaded by every test and
`always_run` for explicit canary test paths. Retain full-suite checkpoints.

## Explain and audit

```bash
pytest-selective affected --config .github/test-impact.json --base origin/main \
  --output selection.json --explanation-output explanation.json
pytest-selective explain --config .github/test-impact.json \
  --test tests/test_prices.py --source src/shop/prices.py
```

To record real file reads, install the optional extra in the Python 3.11+ test
environment and run a representative suite:

```bash
pip install "pytest-selective[audit]"
pytest -p pytest_selective.impact_audit_plugin --impact-audit-dir impact-audit
pytest-selective audit --config .github/test-impact.json --records impact-audit
```

Audit results cover executed paths, not every possible execution. Declare missing
edges at their readers. See [evidence and limitations](evidence.md).

### Custom and nested pytest configuration

The policy fingerprints cover conventional pytest configuration names, including
`pytest.toml`, `.pytest.toml`, `.pytest.ini` and nested candidates. Empty candidates
are included because their presence can change pytest's root and precedence.
Changes require reviewing and refreshing `pytest_policy`; until then planning
fails safely and the CI action runs the complete configured roots.

If your test command uses `pytest -c ci/custom.conf`, add
`"pytest_config_files": ["ci/custom.conf"]` to the selector config **before**
running `fingerprints`. These are literal repository-relative POSIX paths, not
globs. Their complete contents are fingerprinted, and plugin references prevent
unsafe dependency-pin narrowing. Missing declared files cannot prove selection.
Keep environment options, dynamically generated configuration and files outside
the repository covered by explicit whole-lane inputs/full execution.
