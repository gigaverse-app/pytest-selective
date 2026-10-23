# Declare file dependencies with sidecars

A test can read a JSON fixture, template, schema, or Python script without
importing it. The import graph cannot infer that read. Declare the input beside
the code that reads it so changing the input selects the right tests.

A **sidecar** is a small YAML file stored beside its reader. Commit it with the
code. pytest-selective understands it directly, including when CI-esta uses
pytest-selective for selection. No application-specific wrapper is needed.

## 1. Try a fixture change

You need Python 3.11+, Git 2.24+, and pytest-selective. These commands use Bash
(including WSL). On PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1` instead.

```bash
mkdir selective-sidecar-demo
cd selective-sidecar-demo
git init
python -m venv .venv
source .venv/bin/activate
python -m pip install "pytest-selective>=0.3,<0.4"
mkdir -p tests/data
```

Create these files. The demo deliberately has no pytest configuration file;
an existing project should first review its
[collection-policy fingerprints](../configuration.md#review-and-record-collection-policy).

### `.gitignore`

```text
.venv/
__pycache__/
.pytest_cache/
plan.json
explanation.json
```

### `impact.json`

```json
{
  "module_roots": ["."],
  "test_roots": ["tests"]
}
```

### `tests/data/prices.json`

```json
{"currency": "USD", "amount": 10}
```

### `tests/test_prices.py`

```python
import json
from pathlib import Path


def test_catalog_price():
    fixture = Path(__file__).parent / "data" / "prices.json"
    price = json.loads(fixture.read_text())
    assert price == {"currency": "USD", "amount": 10}
```

### `tests/test_health.py`

```python
def test_health():
    assert 2 + 2 == 4
```

### `tests/test_prices.py.gv-dependency.yaml`

```yaml
dependencies:
  - inputs: ["data/prices.json"]
    kind: content
    reason: The price test reads this JSON fixture.
```

Append `.gv-dependency.yaml` to the reader's **complete filename**, including
`.py`. A file sidecar already identifies its reader, so do not add `readers`.

Run the full suite and commit the passing baseline. Git needs your normal
author name and email configured.

```bash
python -m pytest --no-selective -q
git add .gitignore impact.json tests
git commit -m "test: add the sidecar example"
```

Both tests should pass. Now change only the fixture:

```bash
python -c 'from pathlib import Path; Path("tests/data/prices.json").write_text("{\"currency\": \"USD\", \"amount\": 11}\n")'
pytest-selective affected --config impact.json --working-tree \
  --output plan.json --explanation-output explanation.json
python -c 'import json; p = json.load(open("plan.json")); print(p["mode"], p["selected"])'
```

Expected selection:

```text
scoped ['tests/test_prices.py']
```

Run the selected test:

```bash
pytest-selective run --config impact.json -- -q
```

This command **should fail**: the fixture now contains 11 while the test expects
10. The failure demonstrates that a non-Python change reaches its test through
the sidecar. The unrelated health test is not executed.

## 2. Check that unrelated documentation skips tests

Restore the fixture and create an unrelated README:

```bash
python -c 'from pathlib import Path; Path("tests/data/prices.json").write_text("{\"currency\": \"USD\", \"amount\": 10}\n"); Path("README.md").write_text("# Shop notes\n")'
pytest-selective affected --config impact.json --working-tree --output plan.json
python -c 'import json; p = json.load(open("plan.json")); print(p["mode"], p["selected"])'
pytest-selective run --config impact.json -- -q
```

Expected plan: `none []`. The runner skips pytest completely. Never turn an
empty selected-path list into a bare `pytest` command, which runs the whole suite.

If a test actually reads README content, declare it as an input. That README
change should select its reader. There is no universal documentation exemption.

## 3. Choose the declaration that fits the reader

| Form | Location | Use it when |
| --- | --- | --- |
| Dependency comment | In the reading Python file | One or two inputs fit naturally beside the code |
| File sidecar | `reader.py.gv-dependency.yaml` | You need an explicit dependency kind or want declarations outside Python |
| Directory manifest | `.gv-dependencies.yaml` | Several related readers share inputs |

Instead of the sidecar above, a comment in `tests/test_prices.py` can declare:

```python
# gv:test-dependency: tests/data/prices.json
```

Comment paths start at the **repository root**, without `//`. Comments use
import-style dependency edges. For JSON there are no Python imports to follow,
so this selects the same test. Prefer a `content` sidecar when inspecting Python
source as text.

For several tests, replace their individual sidecars with
`tests/.gv-dependencies.yaml`:

```yaml
dependencies:
  - readers: ["test_prices.py", "test_receipts.py"]
    inputs: ["data/prices.json"]
    kind: content
    reason: Both tests read the catalog fixture.
```

This example assumes `test_receipts.py` exists. Directory rules require
`readers`; file sidecars forbid it. Both reader and input patterns in a manifest
are relative to its directory. `//` anchors either pattern at the repository
root, for example `//schemas/receipt.json`. Do not use `../` to reach another
directory.

### Reading content versus executing Python

| Input use | Kind | What changes can select the reader |
| --- | --- | --- |
| Read JSON, SQL, HTML, or a schema | `content` | Changes to that input's bytes |
| Scan Python text or its AST | `content` | Changes to scanned files, without following their imports |
| Dynamically import a Python module | `import` | Changes to the module or its declared/imported dependencies |
| Execute a Python helper in a subprocess | `import` | Changes to the helper or dependencies the graph can trace from it |

`import` is the default, but writing the kind explicitly makes review easier.
For a test that runs `scripts/build_catalog.py`, use:

```yaml
dependencies:
  - inputs: ["//scripts/build_catalog.py"]
    kind: import
    reason: Executes the catalog builder in a Python subprocess.
```

If that script imports `shop.prices`, changing `shop.prices` must also select
the test. Declaring the script as `content` would omit that transitive execution
dependency. Declare additional runtime file reads beside the helper itself;
normal importers inherit the helper's dependencies.

For a guard that walks `src/` and parses Python syntax, use a file sidecar like:

```yaml
dependencies:
  - inputs: ["//src/**/*.py"]
    kind: content
    reason: Scans all production Python source for forbidden calls.
```

A newly added Python file under `src/` is covered too. `src/README.md` is outside
this declared scan. Confirm the guard actually reaches `src/`; asserting the
directory exists prevents a wrong repository-root calculation from silently
scanning nothing.

## 4. Keep patterns precise

Sidecars and comments support `*`, `?`, and whole-segment `**`. An ordinary `*`
does not cross `/`; `**` spans zero or more directories. Use forward slashes on
all platforms. Brace expansion, character classes, backslashes, absolute system
paths, and `.` or `..` segments are not supported.

Each pattern must match at least one file in the Git snapshot being analyzed.
Use committed files for CI; `--working-tree` also includes staged, unstaged, and
nonignored untracked local files. When deleting the last matching input, update
its declaration in the same change. Selection considers both base and head
dependencies so removing a dependency does not erase its former readers from
the comparison.

Avoid `inputs: ["//**"]` or `always_run` as substitutes for discovering inputs.
`always_run` selects those tests on every nonempty change, including unrelated
docs. Keep the default global dependency/configuration inputs: lockfile and
pytest-policy changes may legitimately require full execution. See
[configuration](../configuration.md) and [whole-lane inputs](../ci.md) when the
entire job shares an environment or execution contract.

A directory manifest edit selects its declared readers. Prefer file sidecars or
small directory manifests to one repository-wide manifest whose edits affect
many unrelated readers.

## 5. Diagnose and verify the route

In the fixture example, this explains the dependency path:

```bash
pytest-selective explain --config impact.json --working-tree \
  --test tests/test_prices.py --source tests/data/prices.json
```

For a real project, check both directions: an actual input selects its reader,
and an unrelated document selects none. Also check helper dependencies, newly
added matching files, and deletion of a previously consumed input. Use real Git
changes and the repository's actual configuration.

| Symptom | Check |
| --- | --- |
| "matches no tracked files" | Spelling, relative versus root paths, ignored files, and which revision is being inspected |
| "directory rule requires readers" | Add `readers` to the `.gv-dependencies.yaml` rule |
| "file sidecar must not specify readers" | Remove `readers`; the filename already identifies the owner |
| A helper's dependency does not select its test | Use `import` for executed Python and declare additional runtime reads at the helper |
| README changes still select scanner tests | Inspect `always_run`, broad input globs, global inputs, and shared conftest dependencies |
| A local declaration seems ignored | Use `--working-tree`; ordinary revision planning reads committed trees |

Malformed declarations, duplicate YAML keys, aliases, and missing owners are
errors to fix. Do not use a stale plan after failure. Keep explicit full runs and
scheduled checkpoints for behavior the graph cannot prove. Runtime read auditing
can help find missing declarations; see
[selection health](../selection-health.md#find-runtime-inputs-missing-from-the-model).

Use these same declarations with the public [test-impact action](../actions.md)
or [whole-lane planner](../ci.md). CI-esta can report and validate the resulting
selection; pytest-selective owns the dependency graph.

