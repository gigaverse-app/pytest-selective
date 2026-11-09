# Selection contract

The contract checks the planner two ways. The Quint model states which tests a change
should select. Independently of the model, the driver also runs pytest's collection on both
trees of every comparison ([runtime_deps.py](runtime_deps.py)), records which repository
files each test file really imports or opens, and requires every test that loaded a changed
file to be selected (`missed` must stay empty). The runtime check can fail even where the
model and the planner agree, which is the point: it is how a rule both of them leave out
shows up.

pytest-selective's central promise, as a [Quint](https://quint.sh) model. After a commit,
the selected tests are exactly the tests that reach a changed file, in the base or the head
tree, through imports, an ancestor `conftest.py` or a `# gv:test-dependency:` comment
(import kind, so it follows the declared file's imports), plus the readers of a changed
file's contents (a `kind: content` sidecar, which does not follow imports). A change to a
global input selects every test. Unparseable Python in either tree is an error. The planner's
graph cache is not part of the promise: no configuration edit, cache restart or damaged cache
entry may change an answer.

[pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect) generates
histories from [selection.qnt](selection.qnt). [conftest.py](conftest.py) replays each step
as a real Git commit in a small fixture repository, then runs `affected()` twice through one
`GraphCache`: against the previous commit, and against the history's first commit, as a pull
request's base and head. Configuration edits, cache restarts and damaged cache entries are
followed by a re-plan of the last commit through the same cache. The plugin compares every
selection with the model's.

| Case | What it checks |
| --- | --- |
| 20 witnesses | transitive edits; a deleted module's former importers; declared reads, added and removed; root and nested conftests; a global input; an added import; a deleted test; a test-root helper module; content reads that do not follow imports; import declarations that do; unparseable source; a reverted import that is no change against the first commit; selection across several commits; narrowed `test_roots` after a cached plan; an extra global input; a damaged cache; a restarted cache |
| 24 samples | seeded random histories of up to 8 operations mixing every action |
| 10 mutants | the planner with base-tree edges dropped, only direct importers followed, global inputs ignored, content reads followed like imports, conftest scope collapsed to the test root, parse errors ignored, every base assumed to be the last planned head, `test_roots` left out of the graph cache key, parsed files cached by path, and cache checksums ignored; each must be caught |
| coverage | every action reached |

```bash
uv run --group quint pytest -c quint.ini . --quint-require-complete   # from this directory
```

The [manifest](quint-connect.json) lists what the model leaves out: first-party pins,
name-scoped modules, deferred strings, Django URLconf policy and plugin-registering test
modules have their own tests in `tests/`.
