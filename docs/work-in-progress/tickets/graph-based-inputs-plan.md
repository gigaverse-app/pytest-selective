# Every input through the graph

Retire when every phase below has shipped and the adopter configs in the
gigaverse-app organization no longer list path globs for environment, workflow or
package inputs.

## Why

Python test selection is already graph based: a changed file reaches tests through
imports, conftest ancestry and declared reads, and a file nothing references selects
nothing. Everything around it is still a path rule:

| Path rule today | What it costs |
| --- | --- |
| Built-in environment policy (`*requirements*.txt`, `**/pyproject.toml`, locks, pytest files) runs every test | A docs site's `documentation/requirements.txt`, a `[tool.ruff]` edit or an unrelated lock bump runs the whole suite |
| `.github/` non-Markdown files are global inputs; `ci.yml#job` inputs are declared by hand | Editing a lint job's file list ran every test in pytest-quint-connect |
| Any changed file under a lane root selects the lane | `dogfood/README.md` started pytest-quint-connect's dogfood lane |
| Lane `inputs` are the only way to gate non-pytest work (builds, smokes) | Every adopter hand-listed file types, and `dir/**/*.ext` silently missed `dir/x.ext` |

Adopters responded with docs-shaped exceptions. Documentation should need none: it
has no edges, so it selects nothing.

## Model

One graph. Nodes are repository files plus **derived nodes** for the parts of
structured files that matter separately. **Targets** are what selection returns:
test files, and named CI targets such as a package build.

```text
changed files ──► differs ──► changed nodes ──► reverse reachability ──► tests + targets ──► lanes
                  (lock, pyproject, workflow, requirements, pytest config)
```

| Structured file | Differ produces | Default edges |
| --- | --- | --- |
| `uv.lock`, `poetry.lock`, `pdm.lock`, `requirements*.txt` | `dist:NAME` for each distribution whose resolved version or source changed | `dist:NAME` → every module that imports its import names (from the graph's unresolved imports); first-party pins keep their installed-file proof |
| `pyproject.toml` | `pyproject:TABLE` for each changed table | dependencies and groups → `dist:` nodes; pytest tables → every test of that project; `readme`, `license-files`, version, build backend → `package:NAME`; known tool tables (`ruff`, `mypy`, `coverage.report`, …) → nothing; unknown tables → every test of that project |
| Workflow YAML | `job:PATH#ID` per changed job, plus `workflow:PATH` for top-level keys | `job` → the lanes its `if:` condition reads; `workflow` → every lane it runs |
| pytest configuration | `pytest-policy:PATH` | every test collected under it (the existing fingerprint check) |

A distribution whose import names cannot be determined, or a file a differ cannot
parse, falls back to every test of its project, with the reason in the report.

**Lanes become sets of targets.** A lane selects when one of its tests or targets is
reached: `{"roots": ["tests"], "targets": ["package"]}`. A file under a lane root
that is neither a test nor reached by the graph does not select it. Undeclared reads
are the read audit's job, which is the contract file selection already relies on.

**Rules customize the graph, not a path list.** One declaration replaces
`dependencies`, `always_run`, `global_inputs`, `ignored_changes` and lane `inputs`:

```json
{"rules": [
  {"when": ["schemas/**"], "select": ["tests/contracts/**"], "reason": "schemas loaded by name"},
  {"when": ["dist:django"], "select": ["lane:integration"], "reason": "service-backed checks"},
  {"when": ["pyproject:tool.mycorp"], "select": ["all"], "reason": "read by our pytest plugin"},
  {"when": ["job:.github/workflows/ci.yml#build"], "select": ["target:package"]}
]}
```

Built-in defaults are named rules an adopter can inspect (`pytest-selective rules`),
override or disable by name. Patterns match like gitignore: `dir/**/x` also matches `dir/x`.

## Phases

Each phase ships on its own, keeps the existing configuration valid, and has
real-Git routing tests plus the Quint selection contract kept green.

- [ ] **1. Lane roots and globs through the graph.** A changed file under a lane root
      selects the lane only as a test file (base or head inventory) or through the
      graph; others are reported as unreferenced. `dir/**/x` matches `dir/x`.
- [ ] **2. Workflows as derived nodes.** Per-job differ for every workflow; a changed
      job selects the lanes its condition reads; top-level changes select every lane
      the workflow runs. Workflows leave the built-in global inputs.
- [ ] **3. `pyproject.toml` as derived nodes.** Table-level differ with the default
      classification above; replaces `pyproject.toml` in the built-in policy.
- [ ] **4. Locks and requirements as `dist:` nodes.** Lock and requirements differs,
      import-name resolution, edges through unresolved imports; generalizes the
      first-party pin narrowing; replaces the remaining built-in environment patterns.
- [ ] **5. Targets and rules.** `package:NAME` derived from build metadata, lane
      `targets`, the unified `rules` syntax with named built-in defaults, and a
      migration that reads every existing field.
- [ ] **6. Adopters.** Release under `v1`, then remove the path globs from the
      gigaverse-app adopters and the documentation-only audit's workarounds.
