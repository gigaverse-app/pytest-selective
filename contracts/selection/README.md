# Selection contract

pytest-selective's central promise, as a [Quint](https://quint.sh) model. After a commit,
the selected tests are exactly the tests that reach a changed file, in the base or the head
tree, through imports, an ancestor `conftest.py` or a `# gv:test-dependency:` comment
(import kind, so it follows the declared file's imports), plus the readers of a changed
file's contents (a `kind: content` sidecar, which does not follow imports). A change to a
global input selects every test. Unparseable Python in either tree is an error.

[pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect) generates
histories from [selection.qnt](selection.qnt). [conftest.py](conftest.py) replays each step
as a real Git commit in a small fixture repository, then runs `affected()` twice through one
`GraphCache`: against the previous commit, and against the history's first commit, as a pull
request's base and head. The plugin compares both selections with the model's.

| Case | What it checks |
| --- | --- |
| 16 witnesses | transitive edits; a deleted module's former importers; declared reads, added and removed; root and nested conftests; a global input; an added import; a deleted test; a test-root helper module; content reads that do not follow imports; import declarations that do; unparseable source; a reverted import that is no change against the first commit; selection across several commits |
| 20 samples | seeded random histories of up to 8 commits mixing every action |
| 7 mutants | the planner with base-tree edges dropped, only direct importers followed, global inputs ignored, content reads followed like imports, conftest scope collapsed to the test root, parse errors ignored, and every base assumed to be the last planned head; each must be caught |
| coverage | every action reached |

```bash
uv run --group quint pytest -c quint.ini . --quint-require-complete   # from this directory
```

The [manifest](quint-connect.json) lists what the model leaves out: first-party pins,
name-scoped modules, deferred strings, Django URLconf policy and plugin-registering test
modules have their own tests in `tests/`.
