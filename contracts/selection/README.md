# Selection contract

pytest-selective's central promise, as a [Quint](https://quint.sh) model: after a
commit, the selected tests are exactly the tests that reach a changed file through
imports, an ancestor `conftest.py` or a declared read, in the base or the head tree,
and a change to a global input selects every test.

[pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect) generates
histories from [selection.qnt](selection.qnt). [conftest.py](conftest.py) replays each step
as a real Git commit in a small fixture repository, runs `affected()` between consecutive
commits through one `GraphCache`, and the plugin compares the selection with the model's.

| Case | What it checks |
| --- | --- |
| 7 witnesses | a transitive edit, a deleted module's former importers, a declared read, a conftest edit, a global input, an added import, a deleted test |
| 12 samples | seeded random histories of up to 6 commits: edits, added and removed imports, deleted and restored files, global input edits |
| 3 mutants | the planner with base-tree edges dropped, with only direct importers followed, and with global inputs ignored; each must be caught |
| coverage | every action reached |

```bash
uv run --group quint pytest -c quint.ini . --quint-require-complete   # from this directory
```

The [manifest](quint-connect.json) lists what the model leaves out: first-party pins,
name-scoped modules, deferred strings, Django URLconf policy and plugin-registering test
modules have their own tests in `tests/`.
