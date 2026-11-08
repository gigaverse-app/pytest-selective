# Every Python input through the graph

Retire when the phases below have shipped and Python adopters no longer list
environment files as path globs.

## Why

Python test selection is graph based: a changed file reaches tests through imports,
conftest ancestry and declared reads, and a file nothing references selects nothing.
The Python environment around it is still a path rule. The built-in policy
(`*requirements*.txt`, `**/pyproject.toml`, locks, pytest files) runs every test. So a
docs site's `documentation/requirements.txt`, a `[tool.ruff]` edit or an unrelated lock
bump runs the whole suite, and adopters answered with docs-shaped exceptions.

## Ownership

pytest-selective answers one question: which Python tests does this change affect?
CI facts that hold for every language live in
[CI-esta](https://github.com/gigaverse-app/ci-esta), the first adoption surface. CI-esta
already calls pytest-selective for Python and Bun's `--changed` for Bun:

| Concern | Owner |
| --- | --- |
| Imports, conftests, declarations, pytest policy | pytest-selective |
| `uv.lock`, `poetry.lock`, `pdm.lock`, `requirements*`, `pyproject.toml` as graph nodes | pytest-selective (Python environment) |
| Workflow jobs, the lanes they run, the files and actions they execute | CI-esta |
| Composing selector results and the workflow graph into lanes and jobs; zero-config lanes; rules | CI-esta |
| Package build and smoke targets | CI-esta, from package inputs this project reports (`readme`, `license-files`, package sources) |

`plan-lanes` keeps working for repositories without CI-esta. It is a Python-only
planner and does not grow a workflow graph.

## Model

Structured Python environment files become **derived nodes** that reach tests through
the same reverse reachability as source files:

| File | Differ produces | Default edges |
| --- | --- | --- |
| `uv.lock`, `poetry.lock`, `pdm.lock`, `requirements*.txt` | `dist:NAME` for each distribution whose resolved version or source changed | `dist:NAME` → every module that imports its import names (the graph's unresolved imports); first-party pins keep their installed-file proof |
| `pyproject.toml` | `pyproject:TABLE` for each changed table | dependencies and groups → `dist:` nodes; pytest tables → every test of that project; `readme`, `license-files`, version and build backend → reported as package inputs; known tool tables (`ruff`, `mypy`, `coverage.report`, …) → nothing; unknown tables → every test of that project |

A distribution whose import names cannot be determined, or a file a differ cannot
parse, falls back to every test of its project, with the reason in the report.
`documentation/requirements.txt` pins packages no test imports, so it selects nothing
without any documentation rule.

## Phases

- [x] **1. Lane roots and globs through the graph** ([#90](https://github.com/gigaverse-app/pytest-selective/pull/90)).
- [ ] **2. `pyproject.toml` as derived nodes.** Table-level differ with the default
      classification above; replaces `pyproject.toml` in the built-in policy.
- [ ] **3. Locks and requirements as `dist:` nodes.** Lock and requirements differs,
      import-name resolution, edges through unresolved imports; generalizes the
      first-party pin narrowing; replaces the remaining built-in environment patterns.
- [ ] **4. A selector contract for CI-esta.** Report affected tests with node-level
      reasons and the package inputs the change touched, so CI-esta can compose lanes
      without a second Python graph.
