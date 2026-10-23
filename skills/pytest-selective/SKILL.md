---
name: pytest-selective
description: Speed up Python pytest workflows with explainable affected-test or whole-lane selection. Use when adopting pytest-selective, narrowing broad CI triggers, or verifying that docs-only changes skip unrelated tests while code changes retain coverage.
license: Apache-2.0
---

# Make Python test selection earn its keep

Work in the user's target repository. Inspect its test commands, collection
policy, services and required checks before changing admission. The target need
not use GitHub Actions; the planner also emits JSON for other runners. For a
non-Python suite, use CI-esta's GitHub Actions reporting when applicable rather
than attempting Python import analysis.

## Choose the smallest useful change

Use the [adoption tutorial and checklist](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/tutorials/adoption-checklist.md)
to record applicable capabilities, routing controls, full-run overrides and
measured results. Mark stages verified, deferred or not applicable; do not add
audits, guards or scheduling merely to fill every box.

- For the local edit/test loop, start with `uv add --dev pytest-selective` and
  `uv run pytest --selective`, preserving the project's normal pytest options.
  This includes working-tree changes and preserves native collection. Use
  `--no-selective` for a full control. If collection/import cost dominates, use
  the pre-collection runner with reviewed configuration instead.
- Use **whole-lane selection** first when a job must retain complete coverage,
  compatibility controls, generated tests or conformance evidence. Keep every
  command and evidence validator inside an admitted lane.
- Use **file selection** for ordinary pytest suites where partial collection is
  valid. Do not apply a whole-suite coverage floor to a subset or lower the floor
  to make selection pass.
- Measure startup/install/service time as well as pytest time. Skip an unaffected
  job before starting its services; skipping pytest after provisioning saves less.

Read [the adoption recipe](references/adoption.md) for the config/CLI sequence.
Use the installed revision's CLI help and public models as the API authority.
Use compatible package ranges and release tags in the proposed CI configuration.

## Preserve the input contract

Map all test roots and review collection-policy fingerprints. Declare templates,
fixtures, generated inputs, dynamic imports, subprocess helpers, plugin startup,
dependency locks, environment configuration and execution workflows that imports
cannot capture. Keep global inputs explicit in consumer lane configs. A blanket
`.github/**` can force every lane for PR templates and reporting edits; deleting
all CI inputs instead would miss real execution changes.

Planning normally reads committed base/head trees. For ordinary local pytest
suites, use `pytest-selective run --config CONFIG -- PYTEST_OPTIONS` or inspect
`affected --working-tree`; these use a private index without committing or
changing the user's staging area. Use full runs for custom collection and
whole-suite coverage requirements. Missing history/operational failures must run the
complete configured roots. Repair invalid declarations; never consume a stale
report after a failed command. A successful `none` plan skips pytest: invoking
pytest with no paths runs the whole suite.

## Audit assumptions and protect the improvement

Use [selection health](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/selection-health.md)
when selection is unexpectedly broad or non-import inputs are uncertain. Inspect
dependency paths and startup floors; record representative runtime reads and
repair missing declarations. Offer expansion/isolation guards where global
fixtures or test imports keep widening the graph. Audits only cover observed paths.
Use the [public root and named actions](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/actions.md)
with named entry points under `gigaverse-app/pytest-selective/actions/NAME@REF`,
and verify the chosen release contains those paths; do not put a new path on an
older tag. When upgrading, migrate old paths to `actions/NAME` together with the
revision; old layouts exist only in their original immutable releases.

## Prove the route before claiming a win

Add consumer regression tests using real Git changes and the actual config:
docs/unrelated metadata skip expensive lanes; source/transitive dependencies,
fixtures, deleted tests, locks and execution workflows keep their required lanes;
missing history and an explicit full override execute the full set. Assert the
selected paths/lanes, not just exit status. Route these tests through declared dependencies on selector configuration,
execution workflows, helpers and the inputs they inspect. Documentation-only PRs
must execute zero tests unless documentation is explicitly consumed. Include
routing/contract tests, wheel/sdist smoke tests, tutorials and separate action
workflows in this inventory; a quality or build job is not an exemption. Metadata
and documentation validation may still run without executing runtime tests.

Use dependency selection for ordinary PRs and pushes, including main. Retain scheduled full checkpoints and an explicit full override. Required
check names must still resolve correctly on the empty route. A planner failure
must not silently make a skipped required test green.

Within the task's authorization, measure a successful selected run and full
control on the same head and checked-out merge revision. Record attempt IDs,
executed jobs, elapsed time, summed runner-seconds and preserved checks. One pair
is an observation, not a universal average or a billing claim. If live CI access
is unavailable, deliver the config, local routing evidence and reproducible
measurement command; label hosted impact unmeasured.

## Deliver

Leave a small reviewable change, routing tests, the input assumptions and a
before/after table with evidence. Follow the user's existing PR/merge scope.
[CI-esta](https://github.com/gigaverse-app/ci-esta) can report GitHub job/step time
and overlapping runs separately; receipt reuse is a distinct optional decision.
Keep the [measured impact](https://github.com/gigaverse-app/ci-esta/blob/main/docs/measured-impact.md)
visible in the report, with linked full/selected controls and a collapsed timeline.
File-count reduction alone cannot establish time savings. Preserve full reruns
when removing broad label triggers. Bun projects use their native runner and
CI-esta's Bun evidence adapter; pytest-selective stays optional for CI-esta.
The [92.3% README runner-time reduction](https://github.com/gigaverse-app/pytest-selective/blob/main/docs/benchmarks/2026-10-22-routing.md)
is a worked example, not a target to promise for the user's repository.


For measured scheduling, use CI-esta's
[JUnit timing feedback](https://github.com/gigaverse-app/ci-esta/blob/main/docs/learned-test-timings.md)
with the selector's complete file inventory. Timing hints change placement,
never eligibility. Measure the dependency critical path before adding shards;
preserve service isolation and compare against existing xdist. Review every
committed pytest configuration, including nested and newly added config files,
before refreshing collection-policy fingerprints.
