# pytest-impacted, pytest-selective and CI-esta

This comparison uses [pytest-impacted at 8670157](https://github.com/promptromp/pytest-impacted/tree/8670157aca529be2f19cdb5df26f5476434db240),
pytest-selective's baseline `12694bf`, and CI-esta's baseline `e9d2792`.
The changes described as adopted below belong to this branch until merged.

pytest-impacted is a useful source of ideas for the local edit/test loop.
pytest-selective owns our dependency analysis and routing. CI-esta consumes that
analysis and measures execution, manages evidence, and checks aggregate CI gates.
It should not grow another dependency graph.

## Side by side

| Capability | pytest-impacted | pytest-selective and CI-esta | Decision |
| --- | --- | --- | --- |
| Uncommitted edits | Staged, unstaged and untracked changes | Previously committed trees only | Adopted: `affected --working-tree` and `run`; private index preserves staging and HEAD |
| Local execution | Standard pytest plugin | Previously planner output needed a separate runner | Adopted: `pytest-selective run` plans before starting pytest and handles an empty plan |
| Collection overhead | Plugin marks unaffected items skipped after collection | Runner passes selected files before collection | Keep early selection: unrelated test modules need not import |
| Branch comparison | Merge-base by default, explicit tip comparison | Explicit base/head; CI supplies the intended base | Preserve explicit CI contract; local runner defaults to HEAD and accepts `--base` |
| Dependency environments | Broad built-in lock, requirements and pytest configuration patterns | Lane defaults covered uv/pyproject; file selection needed declarations | Adopted shared environment defaults for file selection and lanes, including deletions |
| Non-Python inputs | Configurable full invalidation globs | Reader-specific declarations, sidecars, and lane input globs | Preserve precision; new `global_inputs` also offers full invalidation |
| Conftest dependencies | Fixture imports; application imports require an option | Ancestor conftests and their transitive imports always apply | Keep conservative existing behavior and scoped-hook review |
| Plugin inputs | pytest_plugins, `-p`, environment plugin names | Literal module references, declared globals, collection fingerprints | Keep explicit startup contract; environment-only plugins still require declaration |
| Deleted dependencies | Links deleted names to current importers | Unions base and head dependency edges | Keep both-tree analysis; local snapshots now use it too |
| Package initializers | Expands package members | Resolves ancestor initializer edges | Already covered by regression tests |
| Source warnings | Parsing ignores execution warnings | Warning-as-error could break analysis | Adopted one warning-stable parser, reused by CI-esta guards |
| Source encodings | Python fallback reads UTF-8 with BOM support | Python bytes parser honors encoding cookies | Preserve encoding-cookie support and verify it in shared-parser tests |
| Invalid Python | Import parsing can return no imports | Selection reports an invalid dependency | Keep actionable failure; do not silently lose dependency edges |
| Parsing cost | Optional Rust batch parser; cheap declaration prefilters | Richer Python analysis of imports, strings, calls and declarations | Adopted declaration prefilter and one AST traversal; measured below |
| Rust acceleration | Accelerates import extraction | Additional AST facts enforce our declarations and narrowing policies | Not a drop-in replacement: retaining a second full parse would erase much of the benefit; no Rust speed claim made here |
| Graph caching | Process-local cached graph, explicit cache clearing | Persistent blob/tree/config/interpreter keys and checksummed records | Preserve content-addressed cache; local snapshots reuse it |
| Traversal | Shared multi-source graph traversal | Shared multi-source closure already exists | No second implementation needed |
| Custom strategies | Executable entry-point extensions | Declarative dependencies, deferred/name scopes and first-party package proofs | Keep the current extension contract; do not auto-load third-party planning code |
| Doctests/custom collectors | Unknown item types are retained | File selection requires reviewed collection policy | Use full runs for custom collection; local runner is for ordinary pytest file suites |
| Explanations | Diagnostics and impacted markers | Dependency paths, graph expansion, floors, runtime read audit | Preserve and reuse the existing report models |
| Whole CI lanes | Standalone file list | Complete lane selection before setup/services | Keep lane selection for conformance suites and coverage floors |
| Timing and reuse | Selection tool | CI-esta reports jobs/steps, learns durations, verifies receipts and gates | Keep owned by CI-esta; selection alone does not prove reusable execution |

Sources: the pinned project's [plugin](https://github.com/promptromp/pytest-impacted/blob/8670157aca529be2f19cdb5df26f5476434db240/pytest_impacted/plugin.py),
[parsing](https://github.com/promptromp/pytest-impacted/blob/8670157aca529be2f19cdb5df26f5476434db240/pytest_impacted/parsing.py),
[strategies](https://github.com/promptromp/pytest-impacted/blob/8670157aca529be2f19cdb5df26f5476434db240/pytest_impacted/strategies.py),
and [graph](https://github.com/promptromp/pytest-impacted/blob/8670157aca529be2f19cdb5df26f5476434db240/pytest_impacted/graph.py).
These ideas informed independent changes; its advertised Rust/astroid speedup is
not a measurement against pytest-selective.

## Measured parser improvement

An actual backend Git tree, `7d8a68058681f7f9b5973e73fe244009d04f69f9`, contains
2,949 Python files, 2,772 unique blobs and 22,698,774 source bytes. On Windows 11
and Python 3.14.7, three uncached parsing samples gave:

| Metric (lower is better) | Before | After |
| --- | ---: | ---: |
| Sample 1 | 9.311s | 4.002s |
| Sample 2 | 8.521s | 4.183s |
| Sample 3 | 7.951s | 4.082s |
| Median | 8.521s | 4.082s |

The median reduction is 52.1%. Both versions produced identical serialized
dependency records: SHA-256
`c476d565e459099fd62dda5710a83d1e1043a0b442977a36ed6e1e58f0e80a62`.
The optimization reuses one breadth-first AST traversal and only tokenizes
comments when the decoded source contains a declaration marker.

These samples include parsing and serialization, excluding Git reads, installs,
cache hits and pytest. They are sequential samples on one machine, not an end-to-end
CI speedup or a statistical confidence interval. An exploratory after run used
a concurrently advanced adopter HEAD and is excluded from this matched-tree
comparison; the fixed tree was rerun explicitly.

Reproduce with [the benchmark script](../scripts/benchmark_parsing.py), passing
the same immutable `--revision` to both versions. Compare `records_sha256` as
well as timings. Never compare mutable HEADs across runs.

## Validation and remaining evidence

Regressions exercise real Git changes and real pytest subprocesses: local edits,
renames/deletions, new tests, forced ignored additions, index preservation,
missing history, empty selections and explicit full execution. Dependency-file
tests cover addition, modification and deletion and assert both selected files
and whole lanes. Parser tests retain syntax errors and encoding behavior.

Hosted CI savings and adopter execution timings are not yet measured for this
branch. Local parser timings do not substitute for those checks. Native pytest
entry-point integration and arbitrary custom collection remain separate from
the new pre-collection CLI runner.
