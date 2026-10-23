# pytest-impacted, pytest-selective and CI-esta

This comparison uses [pytest-impacted at 8670157](https://github.com/promptromp/pytest-impacted/tree/8670157aca529be2f19cdb5df26f5476434db240),
with pytest-selective baseline `12694bf` and CI-esta baseline `e9d2792` in the
original pass. Those improvements shipped in the 0.1 releases. The follow-up
below compares current upstream with pytest-selective 0.1.1 and measures the
new work at explicit commits. CI-esta consumes the shared planner and sharding code.
Use the release notes to check availability in an older installed version.
The benchmark revisions remain frozen for reproducibility.

pytest-impacted is a useful source of ideas for the local edit/test loop.
pytest-selective owns our dependency analysis and routing. CI-esta consumes that
analysis and measures execution, manages evidence, and checks aggregate CI gates.
It should not grow another dependency graph.

## Side by side

| Capability | pytest-impacted | pytest-selective and CI-esta | Decision |
| --- | --- | --- | --- |
| Uncommitted edits | Staged, unstaged and untracked changes | Previously committed trees only | Adopted: `affected --working-tree` and `run`; private index preserves staging and HEAD |
| Local execution | Standard pytest plugin | Native `pytest --selective` and a pre-collection runner | Adopted opt-in plugin registration, CLI/ini options and conservative item handling; both interfaces reuse the same planner |
| Collection overhead | Plugin marks unaffected items skipped after collection | Native plugin deselects after collection; runner passes selected files before collection | Choose native pytest compatibility or the runner's import savings |
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
| Rust acceleration | Ruff parser and Rayon batch import extraction | Full facts include strings, calls, declarations and syntax errors | Measured the extension; adopted bounded parallel full parsing while retaining encoding/error semantics |
| Plugin declarations | Explicit `pytest_plugins` analysis | Generic strings previously missed undotted/comma-separated names | Adopted recursive declaration analysis with session-wide effects; computed values retain full-run fallback |
| Collection prerequisites | Plugins are registered during collection | File selection and independent shards can omit the registering test module | Retain registration modules and keep collection-dependent files in one session |
| Graph caching | Process-local cached graph, explicit cache clearing | Persistent blob/tree/config/interpreter keys and checksummed records | Preserve content-addressed cache; local snapshots reuse it |
| Traversal | Shared multi-source graph traversal | Shared multi-source closure already exists | No second implementation needed |
| Custom strategies | Executable entry-point extensions | Declarative dependencies, deferred/name scopes and first-party package proofs | Keep the current extension contract; do not auto-load third-party planning code |
| Doctests/custom collectors | Unknown item types are retained | Native plugin retains doctests, unknown items and files outside its graph | Runner still requires reviewed collection policy; native mode preserves collection |
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

The final implementation also replayed the same backend tree through the actual
graph cache, opening a fresh cache connection for each step:

| Cache state | Graph construction time | Parsed blobs | Snapshot hits |
| --- | ---: | ---: | ---: |
| Empty cache | 7.719s | 2,772 | 0 |
| Identical tree, persisted cache | 0.049s | 0 | 1 |
| One test gains a comment | 2.250s | 1 | 0 |

All three snapshots contain 982 test files. These are single observations, not
before/after speedups. The incremental tree is
`2ff7876d8f55caaec1e54b13357e6dcf894dd538`; it changes only
`tests/internals/test_test_file_isolation.py`. Collection-policy fingerprints
were refreshed in the in-memory measurement configuration to match the frozen
tree; no adopter configuration or checkout was changed. Persistent blob reuse
already existed and remains intact after the parsing optimization.

## Identical change replay

The [comparison script](../scripts/compare_impacted.py) runs both installed
selectors against the same disposable Git repositories. At the pinned reference
revision, all seven cases agree when pytest-impacted's `conftest_imports=True`
option is enabled:

| Working-tree change | Expected and observed selection |
| --- | --- |
| Transitive application dependency | Its importing test |
| Deleted application dependency | Its former importing test |
| New requirements file | Both tests |
| Documentation only | No tests |
| New untracked test | The new test |
| Package initializer | The package's importing test |
| Application dependency imported only by a conftest | The conftest's descendant test |

For the last case, pytest-impacted's default settings select no tests. Our
existing conservative conftest behavior selects the descendant without an extra
option. This is a correctness reason to retain that behavior, not a claim that
the seven scenarios exhaust either selector's semantics. Run the script in an
environment containing both revisions with `--output comparison.json`.

## Validation and remaining evidence

Regressions exercise real Git changes and real pytest subprocesses: local edits,
renames/deletions, new tests, forced ignored additions, index preservation,
missing history, empty selections and explicit full execution. Dependency-file
tests cover addition, modification and deletion and assert both selected files
and whole lanes. Parser tests retain syntax errors and encoding behavior.

The parser samples above measure parser work only. Separate hosted execution
evidence is published in [the Windows report](benchmarks/2026-10-23-windows-saleor.md);
do not attribute that whole-workflow improvement to parsing alone.
Hosted savings for the new follow-up remain unmeasured. Previous release/adopter
validation is separate evidence; these local graph timings do not substitute for
hosted execution checks. The native
pytest entry point now complements the pre-collection CLI runner; it makes no
additional collection-time speedup claim. See [native plugin behavior](local-development.md).

## Follow-up: plugin correctness and complete graph performance

Real pytest subprocesses reproduced three failures in the previous selector:

| Scenario | Before | After |
| --- | --- | --- |
| Undotted plugin depends on changed code | Both tests fail under pytest; selection returns zero files | Both dependent tests run |
| A selected test uses a plugin registered by another test module | Registering module omitted; fixture missing | Registering module remains in the selected collection |
| Those files go to independent shard processes | Fixture missing in the consumer shard | One complete pytest session; no duplicate tests |

Static registrations are followed recursively. Unknown declarations, alias
mutation and unsupported binding forms cannot prove scope, so callers use their
existing full-run fallback. Root-conftest registration still permits parallel
shards because pytest loads the conftest in every session. Test-module
registration has a correctness cost: it requires one collection session.

The performance comparison starts at `389e797`, which already contains the
plugin correctness changes, and ends at `b1062fe`. Both analyze the same backend
trees listed above, with the same in-memory collection policy. Three sequential
samples on Windows 11 / Python 3.14.7, using four parser workers for the large
cache miss, produced these seconds (lower is better):

| Graph operation | Before samples | After samples | Median before | Median after |
| --- | --- | --- | ---: | ---: |
| Cold | 6.224, 6.203, 6.060 | 3.328, 3.350, 3.261 | 6.203 | 3.328 |
| Same tree cached | 0.0294, 0.0285, 0.0281 | 0.0304, 0.0280, 0.0277 | 0.0285 | 0.0280 |
| One-file incremental | 1.866, 1.791, 1.787 | 1.667, 1.415, 1.395 | 1.791 | 1.415 |

Cold graph construction falls 46.3%; incremental construction falls 21.0% in
this scenario. Dedicated subprocesses parse immutable blobs with the existing
complete parser. The parent owns SQLite and validates worker versions and
complete responses; worker failures retry serially. Small misses stay serial.
Deferred routing assignments now share one analysis per blob and policy, cached
by both inputs; consumer discovery and validation still run on each new tree.

Complete serialized graph hashes match before and after in every sample:

- Base: `9812f9a3ec63a141f0554ac79bf46e0d194fdf3175e7260cc58b63f293b872e4`
- Incremental: `b7675517fec02c35608448fcd24157425b12748f613f77dc33847340c75b61d7`

Reproduce using [benchmark_graph.py](../scripts/benchmark_graph.py), supplying
the same `--repo`, `--base`, `--head` and `--output` to each analyzer revision.
This measures graph construction including Git, cache reads and worker startup.
It excludes dependency installation and test execution; three samples on one
machine establish neither a universal speedup nor a billing reduction.

## What the optional Rust extension actually provides

`pytest-impacted[fast]` installs `pytest-impacted-rs`. Version 0.35.0 installed
successfully on this Windows/Python 3.14 machine. Its public API accepts file
paths and returns imports, with Ruff parsing and Rayon parallelism. It has no
Git-blob/source-bytes API or complete dependency-facts result.

An exploratory run of the same 2,772 blobs measured 1.767s to materialize files,
then 1.317s, 0.053s and 0.047s for native import extraction. The later calls had
warm runtime/filesystem caches. These calls do less work than our parser and
are not an end-to-end speed comparison. Reproduce with
[benchmark_rust.py](../scripts/benchmark_rust.py).

The extension also returned an empty import list for both invalid Python and a
valid Latin-1 file containing `import application`. Our parser preserves the
syntax diagnostic and the latter dependency. Its current result therefore
cannot safely replace the complete parser. The measured native speed makes a
richer optional backend worth pursuing: it needs source-byte input, explicit
error reporting, Python encoding support, and all existing dependency facts.
No Rust runtime dependency is added by this follow-up.
