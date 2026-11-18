![pytest-selective: Run affected Python tests. See why they matter.](https://raw.githubusercontent.com/gigaverse-app/pytest-selective/main/docs/assets/banner.png?v=17de2a0b7412)

# pytest-selective

Change one Python function and run the tests that depend on it. pytest-selective follows the change through your code, so you can catch a regression in a caller without waiting for the whole suite.

Free and open source under Apache 2.0. Use it locally with your existing pytest suite or add it to CI.

## Try it on your next edit

In a project with a passing pytest suite, install the plugin:

```sh
uv add --dev pytest-selective
```

Commit the dependency and lockfile changes. Edit an application function, then run:

```sh
uv run pytest --selective
```

Read the selection summary to see which files your edit affected. The selector follows indirect imports too. If scope is uncertain, it runs the full suite. Use `uv run pytest --no-selective` for a full comparison.

In CI you can move selection ahead of collection and service startup. A documentation edit can then skip a database job before you pay to start its runner.

## Add it to CI with one prompt

Paste this into your coding agent from the root of your repository:

```text
Set up pytest-selective in this repository. Fetch https://pytest-selective.readthedocs.io/en/latest/agent-setup.md and follow it.
```

Your agent opens a pull request with the workflow changes and measurements. You can review which checks ran, how long you waited, and how much runner time they used.

[Quickstart](https://pytest-selective.readthedocs.io/en/latest/docs/tutorial/) · [Adoption guide](https://pytest-selective.readthedocs.io/en/latest/docs/tutorials/adoption-checklist/) · [GitHub Actions reference](https://pytest-selective.readthedocs.io/en/latest/docs/actions/)

## How much time could you save?

Change a MongoDB test and keep the database checks that matter. In pytest-obligation, that edit passed CI in **54 seconds instead of 5m22s**, using **93 runner-seconds instead of 1,602**. [Explore the measured examples](https://pytest-selective.readthedocs.io/en/latest/ecosystem/).

[Declare runtime dependencies](declarations/README.md) · [Add caching, evidence reuse and balanced shards with CI-esta](https://ci-esta.readthedocs.io/en/latest/) · [Contribute](CONTRIBUTING.md) · [License](LICENSE)

[Detailed adoption reference](ADOPTION-REFERENCE.md) — installation options, selection guarantees, benchmarks and tool comparisons.

<details>
<summary>Project quality checks</summary>

<!-- pytest-quint-connect:start -->
<!-- pytest-quint-connect:contracts selection -->
<a href="https://github.com/gigaverse-app/pytest-quint-connect#impact"><picture><source media="(prefers-color-scheme: dark)" srcset="https://pytest-quint-connect-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=f8e41d50ca4018845c305f2f0dbd1cfd6d9b281e53b352490af53154a54e6265&amp;name=gigaverse-app%2Fpytest-selective&amp;theme=dark"><img alt="What pytest-quint-connect&#x27;s contracts caught in gigaverse-app/pytest-selective&#x27;s pull requests" src="https://pytest-quint-connect-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=f8e41d50ca4018845c305f2f0dbd1cfd6d9b281e53b352490af53154a54e6265&amp;name=gigaverse-app%2Fpytest-selective" width="100%"></picture></a>

<a href="https://github.com/gigaverse-app/pytest-quint-connect" title="Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug"><img alt="Quint contracts: 1 contract passed · 49 histories · 14/14 planted bugs caught" src="https://img.shields.io/badge/Quint_contracts-1_contract_passed_%C2%B7_49_histories_%C2%B7_14%2F14_planted_bugs_caught-brightgreen"></a>

| | Contract | Cases passed | [Planted bugs caught](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/why.md#proof-that-the-tests-can-fail "Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug") |
| :-: | :-- | --: | --: |
| ✅ | `selection` `test_selection_contract.py::test_selection`<br><sub>49 histories (25 witnesses, 24 samples, seed 11) · every action covered · Quint 0.33.1</sub> | 64/64 | 14/14 |

**Bugs this contract found**

1. **A test that does `from pkg import *` was not selected when a submodule pkg lists in __all__ changed.** Fixed in #94 · found by the runtime check (pytest loaded the changed file, the planner skipped the test), after an adversarial review reported it; witness starImportFollowsAllTest · regression test `tests/testing/test_impact_graph.py::test_star_import_reaches_the_submodules_its_package_lists_in_all`. 1 of 49 histories diverge when [planted bug](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/why.md#proof-that-the-tests-can-fail "Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug") `star-exports-ignored` (Reintroduces the star-import bug: from pkg import * no longer reaches the submodules pkg lists in __all__) reintroduces it; first caught by `witness-starImportFollowsAllTest` at state 2, after `edit(file='alpha', target='')`.
1. **Editing a plugin loaded by `addopts = -p NAME` selected no test, though it is loaded into every session.** Fixed in #95 · found by the runtime check (pytest loaded the changed file, the planner skipped the test), after an adversarial review reported it; witness commandLinePluginSelectsEveryTestTest and random histories · regression test `tests/testing/test_impact_graph.py::test_command_line_plugin_in_addopts_reaches_every_test`. 2 of 49 histories diverge when [planted bug](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/why.md#proof-that-the-tests-can-fail "Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug") `addopts-plugins-ignored` (Reintroduces the plugin bug: a plugin named by -p in addopts is no longer a dependency of every test) reintroduces it; first caught by `witness-commandLinePluginSelectsEveryTestTest` at state 1, after `edit(file='plugin', target='')`.
1. **A bare `import helpers` resolved by pytest's default import mode was not followed, so editing tests/helpers.py selected nothing.** Fixed in #96 · found by the runtime check (pytest loaded the changed file, the planner skipped the test), after an adversarial review reported it; witness bareTestImportFollowsPrependModeTest · regression test `tests/testing/test_impact_graph.py::test_bare_import_resolves_from_the_importers_prepend_mode_base_directory`. 1 of 49 histories diverge when [planted bug](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/why.md#proof-that-the-tests-can-fail "Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug") `prepend-roots-ignored` (Reintroduces the import-mode bug: imports no longer resolve from the directories pytest prepends to sys.path) reintroduces it; first caught by `witness-bareTestImportFollowsPrependModeTest` at state 2, after `edit(file='helper', target='')`.
1. **A test that read a tracked file with open() and a literal path was not selected when that file changed.** Fixed in #106 · found by the runtime check (pytest opened the changed file, the planner skipped the test), after an adversarial review reported it; witness literalPathReadTest · regression test `tests/testing/test_impact_graph.py::test_reading_a_tracked_file_by_literal_path_selects_the_reader`. 1 of 49 histories diverge when [planted bug](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/why.md#proof-that-the-tests-can-fail "Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug") `literal-reads-ignored` (Reintroduces the literal-read bug: open('data/table.json') no longer makes the reader depend on that file) reintroduces it; first caught by `witness-literalPathReadTest` at state 2, after `edit(file='table', target='')`.

**[Planted bugs](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/why.md#proof-that-the-tests-can-fail "Mutants: deliberately broken copies of the code. Each must make some history diverge, proving the contract would notice that kind of bug") this contract catches**

- `head-edges-only`: Plans with the head tree's edges only, so a deleted module's former importers are not selected. Caught by `witness-deletedModuleSelectsFormerImportersTest` at state 1, after `remove(file='beta', target='')`.
- `direct-importers-only`: Follows only files that import a changed file directly, not their importers. Caught by `witness-transitiveEditTest` at state 1, after `edit(file='beta', target='')`.
- `global-inputs-ignored`: Treats requirements.txt like any unreferenced file instead of selecting every test. Caught by `witness-globalInputSelectsEveryTestTest` at state 1, after `touchGlobal(file='', target='')`.
- `content-follows-imports`: Reads a kind: content declaration as an import, so it also follows the read file's imports. Caught by `witness-contentReadIsNotTransitiveTest` at state 2, after `edit(file='beta', target='')`.
- `conftest-scope-collapsed`: Scopes every conftest to the top test directory, so tests/sub/conftest.py reaches every test. Caught by `witness-nestedConftestSelectsItsSubtreeTest` at state 1, after `edit(file='subconftest', target='')`.
- `parse-errors-ignored`: Treats an unparseable file as importing nothing instead of stopping with an error. Caught by `witness-unparseableSourceIsAnErrorTest` at state 1, after `breakSyntax(file='beta', target='')`.
- `assumes-consecutive-base`: Plans every run against the head it planned last, which is right only between neighbouring commits. Caught by `witness-transitiveEditTest` at state 1, after `edit(file='beta', target='')`.
- `cache-key-omits-test-roots`: Leaves test_roots out of the cached graph's key, so a graph built for the old roots is reused after they change. Caught by `witness-narrowedTestRootsReplanFromScratchTest` at state 2, after `toggleConfig(file='narrow', target='')`.
- `parse-cache-keyed-by-path`: Caches parsed files by path instead of content, so an edited file keeps its old imports. Caught by `witness-importDeclarationFollowsImportsTest` at state 3, after `edit(file='beta', target='')`.
- `cache-checksum-ignored`: Trusts a stored graph without checking its checksum, so a damaged entry is used as if it were valid. Caught by `witness-damagedCacheIsRebuiltTest` at state 2, after `corrupt(file='', target='')`.

<sub>Generated by [pytest-quint-connect](https://github.com/gigaverse-app/pytest-quint-connect) from contract receipts; [what a passing run proves](https://github.com/gigaverse-app/pytest-quint-connect/blob/main/docs/limits.md).</sub>
<!-- pytest-quint-connect:end -->

<!-- dry-lint-progress:start -->
<a href="https://github.com/gigaverse-app/dry-lint"><picture><source media="(prefers-color-scheme: dark)" srcset="https://dry-lint-counter.gigaverse-oss.workers.dev/v1/sign.svg?theme=dark&amp;key=f8e41d50ca4018845c305f2f0dbd1cfd6d9b281e53b352490af53154a54e6265&amp;name=gigaverse-app%2Fpytest-selective&amp;cleaned=9&amp;remaining=0&amp;dismissed=0"><img alt="dry-lint in gigaverse-app/pytest-selective: new duplicates kept out of its pull requests, 9 old duplicates cleaned up, 0 remaining" src="https://dry-lint-counter.gigaverse-oss.workers.dev/v1/sign.svg?key=f8e41d50ca4018845c305f2f0dbd1cfd6d9b281e53b352490af53154a54e6265&amp;name=gigaverse-app%2Fpytest-selective&amp;cleaned=9&amp;remaining=0&amp;dismissed=0" width="100%"></picture></a>

**Reviewed duplication debt** · Counts from the committed baselines.

| Accepted pairs | Remaining | Retired | Dismissed |
| :-- | --: | --: | --: |
| Functions | 0 | 9 | 0 |
| Models | Not initialized | — | — |

[Accepted backlog](.dry-lint/baseline.json) · [Weekly audit](https://github.com/gigaverse-app/pytest-selective/actions/workflows/dry-lint-audit.yml)

Retired means a side was removed, or (functions only) the judge now finds the pair separate. It is not a count of refactors. Dismissals stay separate; an uninitialized model baseline is unknown.
<!-- dry-lint-progress:end -->

</details>
