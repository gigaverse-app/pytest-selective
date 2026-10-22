# Learnings from pytest-impacted

Reference: promptromp/pytest-impacted at 8670157aca529be2f19cdb5df26f5476434db240.
Baseline: pytest-selective 12694bf; CI-esta e9d2792.

- [x] Source analysis preserves dependency edges under warning-as-error settings;
  exercise real Git selection, deferred declarations, explanations and import guards.
- [x] A single source parser owns warning and encoding policy; genuine syntax
  failures retain their existing diagnostics.
- [x] Measure cold, warm and incremental analysis and adopt proven reductions in
  repeated work without changing selected files.
- [x] Local working-tree selection includes staged, unstaged, deleted and untracked
  inputs while preserving the user's index and existing committed-tree behavior.
- [x] Compare pytest collection, dependency invalidation, caching, configuration,
  extensibility and failure handling; record each adoption or justified difference.
- [x] Run installed CLI scenarios and adopter routing controls, then reconcile
  local evidence and hosted verification separately.

Initial Windows baseline: 241 passed, 9 failed in 48.35s. All nine failures launch
the Windows WSL bash shim against Windows paths. Retry with Git for Windows bash
on PATH before attributing these failures to source changes.

Parser batch: the selection regression failed both warning policies before the
fix; CI-esta boundary regressions failed all four source/test and error/always
combinations. Shared `ast_imports.parse_ast` now owns AST parsing across selection,
name scopes, expansion, isolation and CI-esta boundaries. Graph cache version 19
invalidates warning-dependent results. Focused selector validation: 374 passed,
2 skipped; added name-scope controls: 4 passed including the selection controls.
CI-esta boundary/config validation: 34 passed, 1 skipped. The CI-esta run used
`uv pip install --no-deps -e ../pytest-selective-impacted` and `uv run --no-sync`
because its locked dependency still points to the previous upstream release.

Core batch: 612 passed, 2 skipped on Windows with Git Bash. After adding the
input-only-lane global-invalidation control, 74 focused tests passed. CI-esta:
1,072 passed on WSL/Linux using the sibling candidate. Windows CI-esta's complete
suite hit POSIX signal/path assumptions (70 failures); the equivalent Linux
suite passed. Both source/wheel distributions installed and ran the tutorial on
Python 3.11 and 3.14. Hooks, metadata validation and builds passed.

Due: 10 consumer contract tests passed. pytest-obligation initially failed 13
routing subcases because its older pin's configuration omitted nested pytest
fingerprints. Reviewed the nested collection settings, refreshed fingerprints,
and added environment-file controls: 13 consumer contract tests passed. The
same nested-policy fixes landed independently on main; the final adopter PR
reuses those regressions instead of keeping a duplicate.

Matched backend parsing: 2,772 unique blobs / 22,698,774 bytes from tree
7d8a68058681f7f9b5973e73fe244009d04f69f9. Three samples each: median 8.521s
before, 4.082s after; identical dependency-record SHA-256. Details and limits:
[comparison](../../comparison-pytest-impacted.md).

Final pinned runtime `7cdab2621185f03689410ba92b84f93fea47e395` passed hosted
selector CI [39868386707](https://github.com/gigaverse-app/pytest-selective/actions/runs/39868386707).
CI-esta `3889852` passed 1,081 Linux tests with the immutable locked archive and
hosted [39869214254](https://github.com/gigaverse-app/ci-esta/actions/runs/39869214254).
Due `7562cb7` passed 15 consumer contracts, hosted
[CI](https://github.com/gigaverse-app/due/actions/runs/39869469000) and
[widget routing](https://github.com/gigaverse-app/due/actions/runs/39869469062).
pytest-obligation passed 13 contracts after integrating the nested-policy fix;
the final merge with its toolkit pin rollout is being checked in
[39869817956](https://github.com/gigaverse-app/pytest-obligation/actions/runs/39869817956).

Seven identical real-Git scenarios agree with pytest-impacted's conservative
conftest option. Its default misses the application-imported conftest case;
pytest-selective retains the affected descendant test. The script and observed
cases are linked from the comparison. Persisted cache replay parses zero blobs
for the same tree and exactly one after a one-file comment change.
