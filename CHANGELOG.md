# Changelog

## [1.4.0](https://github.com/gigaverse-app/pytest-selective/compare/v1.3.0...v1.4.0) (2026-11-09)


### Features

* **lanes:** partition test roots by filename patterns ([27c10ec](https://github.com/gigaverse-app/pytest-selective/commit/27c10ec608f052a36f58d9b10730048ab9d38598))

## [1.3.0](https://github.com/gigaverse-app/pytest-selective/compare/v1.2.0...v1.3.0) (2026-11-09)


### Features

* **audit:** show how many tests each written declaration selects ([#124](https://github.com/gigaverse-app/pytest-selective/issues/124)) ([b660301](https://github.com/gigaverse-app/pytest-selective/commit/b660301be82aefb04fdc79202dc83067c28d7eb1))


### Bug fixes

* agent setup round 3, from a third adoption trial ([#127](https://github.com/gigaverse-app/pytest-selective/issues/127)) ([a82bea9](https://github.com/gigaverse-app/pytest-selective/commit/a82bea9f607abcb3ed68009571202ad8b7726c7e))
* **selection:** keep every module a pytest11 entry-point name maps to ([#122](https://github.com/gigaverse-app/pytest-selective/issues/122)) ([acb6649](https://github.com/gigaverse-app/pytest-selective/commit/acb66492c6440621387e0506c1d0071a5a48979c))
* **selection:** plan a pull request against its merge commit's actual base ([#119](https://github.com/gigaverse-app/pytest-selective/issues/119)) ([276cec8](https://github.com/gigaverse-app/pytest-selective/commit/276cec84f65c889a1820fd5a001a3a4aca8b7e0d))

## [1.2.0](https://github.com/gigaverse-app/pytest-selective/compare/v1.1.2...v1.2.0) (2026-11-09)


### Features

* **ci:** share plan execution and reduce matrix instrumentation ([1fe0f36](https://github.com/gigaverse-app/pytest-selective/commit/1fe0f36463d4354a99ea3f45406825fa728a12c2))

## [1.1.2](https://github.com/gigaverse-app/pytest-selective/compare/v1.1.1...v1.1.2) (2026-11-09)


### Bug fixes

* agent setup round 2, from a second adoption trial ([#114](https://github.com/gigaverse-app/pytest-selective/issues/114)) ([45d4afe](https://github.com/gigaverse-app/pytest-selective/commit/45d4afe76cde9f6093519d97000244c6c06b157d))

## [1.1.1](https://github.com/gigaverse-app/pytest-selective/compare/v1.1.0...v1.1.1) (2026-11-09)


### Bug fixes

* **selection:** follow file reads that name a tracked file by literal path ([#106](https://github.com/gigaverse-app/pytest-selective/issues/106)) ([5c534c4](https://github.com/gigaverse-app/pytest-selective/commit/5c534c48d3d098fb0e659973e2e40b410198af19))

## [1.1.0](https://github.com/gigaverse-app/pytest-selective/compare/v1.0.0...v1.1.0) (2026-11-09)


### Features

* one-prompt agent setup, and fixes from a real adoption trial ([#105](https://github.com/gigaverse-app/pytest-selective/issues/105)) ([27c4578](https://github.com/gigaverse-app/pytest-selective/commit/27c45786f1a6a349409eb2a083510e4e9a9180d3))


### Bug fixes

* **lanes:** select only lanes holding graph tests when every graph test is affected ([#102](https://github.com/gigaverse-app/pytest-selective/issues/102)) ([d6f22b8](https://github.com/gigaverse-app/pytest-selective/commit/d6f22b8f93773a4b2e60b2b8ad9d4b26762b2d2f))
* **selection:** resolve imports from the directories pytest's default import mode adds to sys.path ([#96](https://github.com/gigaverse-app/pytest-selective/issues/96)) ([d825176](https://github.com/gigaverse-app/pytest-selective/commit/d825176eb6d259733ec8132ba98ac327be15eb72))

## [1.0.0](https://github.com/gigaverse-app/pytest-selective/compare/v0.4.3...v1.0.0) (2026-11-08)


### Bug fixes

* **ci:** streamline dogfood checks and prepare the 1.0 release ([#97](https://github.com/gigaverse-app/pytest-selective/issues/97)) ([5c79edc](https://github.com/gigaverse-app/pytest-selective/commit/5c79edcc2e234ccd90902ef001d2852cf7ecfdbc))
* **selection:** follow star imports to the submodules a package lists in __all__ ([#94](https://github.com/gigaverse-app/pytest-selective/issues/94)) ([ea02fbf](https://github.com/gigaverse-app/pytest-selective/commit/ea02fbfe85c2d5b6e8685a4b159215d421f78653))

## [0.4.3](https://github.com/gigaverse-app/pytest-selective/compare/v0.4.2...v0.4.3) (2026-11-08)


### Bug fixes

* **lanes:** select lanes through the graph and match ** like gitignore ([#90](https://github.com/gigaverse-app/pytest-selective/issues/90)) ([107b021](https://github.com/gigaverse-app/pytest-selective/commit/107b0212ed741ac72c36a39cc864906eca75d1ab))

## [0.4.2](https://github.com/gigaverse-app/pytest-selective/compare/v0.4.1...v0.4.2) (2026-11-07)


### Bug fixes

* consolidate duplicated selection helpers and retire baseline debt ([#77](https://github.com/gigaverse-app/pytest-selective/issues/77)) ([a7427bf](https://github.com/gigaverse-app/pytest-selective/commit/a7427bf6f550789a835a38f3326b8a971bef114f))

## [0.4.1](https://github.com/gigaverse-app/pytest-selective/compare/v0.4.0...v0.4.1) (2026-10-24)


### Bug fixes

* **selection:** preserve rerun scope and record planner reasons ([29d1df8](https://github.com/gigaverse-app/pytest-selective/commit/29d1df806816203bad1e7a4a53f38b7e75c1d268))

## [0.4.0](https://github.com/gigaverse-app/pytest-selective/compare/v0.3.0...v0.4.0) (2026-10-24)


### Features

* **actions:** simplify selection adoption with shared defaults ([#63](https://github.com/gigaverse-app/pytest-selective/issues/63)) ([85e082d](https://github.com/gigaverse-app/pytest-selective/commit/85e082dfdbcf2f8c02ac3de38613c818cb749807))

## [0.3.0](https://github.com/gigaverse-app/pytest-selective/compare/v0.2.0...v0.3.0) (2026-10-23)


### ⚠ BREAKING CHANGES

* **actions:** named action callers upgrading from older layouts must replace `.github/actions/NAME` or `NAME` with `actions/NAME` and select a revision containing that path.

### Features

* **actions:** group public entry points under actions directory ([#44](https://github.com/gigaverse-app/pytest-selective/issues/44)) ([236aefc](https://github.com/gigaverse-app/pytest-selective/commit/236aefc83d9f0ee1696a5ffa29fc83cbcc4a53dc))


### Bug fixes

* **ci:** dogfood dependency-based test selection ([#57](https://github.com/gigaverse-app/pytest-selective/issues/57)) ([76afb69](https://github.com/gigaverse-app/pytest-selective/commit/76afb69cea84681bd661ec2bfff7be857b434129))
* **ci:** select all runtime tests by declared dependencies ([9673e50](https://github.com/gigaverse-app/pytest-selective/commit/9673e50dd8a709db9347d2e325da242aca96cece))
* **docs:** refresh cached artwork when branding changes ([5726530](https://github.com/gigaverse-app/pytest-selective/commit/5726530a445099e7cf24a1a7a89016fed0270308))


### Refactoring

* **actions:** move implementations into the public actions directory ([#46](https://github.com/gigaverse-app/pytest-selective/issues/46)) ([bd5aae3](https://github.com/gigaverse-app/pytest-selective/commit/bd5aae32176ae83b121d2353f40b562642184cd8))

## [0.2.0](https://github.com/gigaverse-app/pytest-selective/compare/v0.1.1...v0.2.0) (2026-10-23)


### Features

* add public action entry points and task-focused onboarding ([#41](https://github.com/gigaverse-app/pytest-selective/issues/41)) ([94da1e6](https://github.com/gigaverse-app/pytest-selective/commit/94da1e6d4088d9ded93ce491dc88993ac140e0ea))


### Bug fixes

* **selection:** preserve plugin sessions and accelerate graph construction ([#42](https://github.com/gigaverse-app/pytest-selective/issues/42)) ([2994c88](https://github.com/gigaverse-app/pytest-selective/commit/2994c887d916a965b78f5ff8d48476abed705e37))

## 0.1.1 (2026-10-23)

- Register a native pytest plugin: `pytest --selective`, ini defaults, optional existing impact JSON, an exact comparison base, and `--no-selective` for full execution.
- Reuse the existing working-tree snapshots and dependency planner; share one plan with xdist workers and preserve unknown collectors, doctests, normal pytest filtering and failure statuses.
- Install pytest as a runtime dependency; retain the audit extra and all CLI/CI interfaces.

## 0.1.0 (2026-10-23)

First PyPI release.

- Run affected local edits before committing with `run` and `affected --working-tree`, preserving the user's Git index and HEAD.
- Share conservative environment-file invalidation between file selection and CI lanes, covering other Python installers as well as uv.
- Reuse one AST traversal and skip unnecessary comment tokenization; real-backend parser records are unchanged with a measured 52.1% median parsing-time reduction.
- Keep source analysis independent of warning-as-error settings through a shared parser used by import guards and CI-esta.
- Preserve explicit global-input precedence over name narrowing, and retry oversized local pytest commands once with complete roots.

- Guard hidden, TOML, nested and explicitly declared pytest configuration against unsafe empty selection; retain full-suite dependency updates for configured plugins.
- Reuse Git tree listings within a process and start fewer Git processes in test fixtures; Windows CI measures coverage on Python 3.14 only.

- Lane inputs can name one workflow job (`.github/workflows/ci.yml#tests`), so edits to other jobs, such as a planner pin bump, no longer run the lane.
- Batch first-party commit probes and avoid redundant Git maintenance in bounded dependency caches.
- Isolate nested audit-test temporary directories to avoid unrelated fixture cleanup.
- Add matched Windows full-suite timing, test inventory and coverage evidence.
- `plan-lanes` uploads its plan as the `test-lane-selection` artifact, which CI-esta renders as the sticky's lane section.

- Guided README, configuration reference, CI integration, and runnable regression tutorial.
- Coverage artifacts, Linux/Windows/macOS CI, minimum-pytest checks, and isolated wheel/sdist smoke tests.
- Locked Ruff pre-commit hooks, local documentation link checks, and dependency updates.
- Version-checked PyPI trusted-publishing workflow and maintainer release guide.

### Initial source extraction

- Git-based Python test selection using both base and head dependency graphs.
- Reader-owned dependency declarations, runtime audits, and selection explanations.
- Cached graph planning and duration-based shard sizing.
- Standalone CLI and GitHub Actions integration.

See [PROVENANCE.md](PROVENANCE.md) for the extraction boundary.
