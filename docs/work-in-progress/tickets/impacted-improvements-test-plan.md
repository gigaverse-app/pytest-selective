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

Final pinned runtime `6c65e923adf9e4283ba64c0db994304b3d426031` passed 624 local
tests (2 skipped) and hosted
[39870754068](https://github.com/gigaverse-app/pytest-selective/actions/runs/39870754068),
including Linux, Windows and macOS on Python 3.11 and 3.14, minimum pytest,
distribution installs and the installed tutorial.
CI-esta `de97e4f` passed 1,081 Linux tests with the immutable locked archive and
hosted [39870853962](https://github.com/gigaverse-app/ci-esta/actions/runs/39870853962).
Due `e657074` passed 15 consumer contracts, hosted
[CI](https://github.com/gigaverse-app/due/actions/runs/39871413040) and
[widget routing](https://github.com/gigaverse-app/due/actions/runs/39871413101).
pytest-obligation `c70bf89` passed 13 contracts and hosted
[39870827024](https://github.com/gigaverse-app/pytest-obligation/actions/runs/39870827024),
including the admitted database, queue, demo and external conformance lanes.

Seven identical real-Git scenarios agree with pytest-impacted's conservative
conftest option. Its default misses the application-imported conftest case;
pytest-selective retains the affected descendant test. The script and observed
cases are linked from the comparison. Persisted cache replay parses zero blobs
for the same tree and exactly one after a one-file comment change.

The next review found two interactions: global matches must use original changed
paths before name narrowing, and a large local selected-file argument list can
exceed Windows process limits. Both global/name-scope controls failed before the
fix; all 112 global, name-scope and first-party controls now pass. The runner
regressions exercise the actual Windows limit and the portable E2BIG recovery
boundary, retaining other errors and retrying only once. The final pins above
include both corrections.

Backend-common `b687c04` passed 95 focused compatibility checks and hosted
[Python tests](https://github.com/gigaverse-app/backend-common/actions/runs/39871010403),
type checking and CI action validation. Before the final pin refresh its broader
Linux suite passed 637 tests (58 skipped). Compatibility cleanup removes stale
private-import inventories, synchronizes action inputs/schema, and checks pins
through the existing canonical migration contract.

The generated backend and AI adoption PRs exposed missing nested pytest-policy
fingerprints. Reviewed the nested settings and repaired the generated branches,
preserving the collection-policy guard. Backend `51781fdae` passes all 193
existing routing/policy controls under Linux. Its unchanged-tree CLI run selects
zero tests from 982 files without fallback. AI `6211347bb` passes 19 routing
controls, including full real-repository Git trees for unchanged/docs-only
selection and changed-policy fallback. Its lockfile control now expects full
selection. The first upgrade can still conservatively run fully against its
base commit's older declarations; a repaired head does not silently approve an
unreviewed base policy. Hosted application results belong to generated adoption
PRs [backend #5500](https://github.com/gigaverse-app/gigaverse-backend/pull/5500)
and [AI #3117](https://github.com/gigaverse-app/gigaverse-ai/pull/3117).
