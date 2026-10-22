# Windows Git performance verification

Keep the complete test inventory, OS/Python matrix, real Git histories, CLI journeys,
coverage collection, and conservative fallback behavior.

- [x] Record full native Windows baseline at a7be2f7 with the repaired coverage wheel metadata.
- [x] Exercise batched probes against real available, absent, duplicate and non-commit objects.
- [x] Run all existing dependency pin, bounded cache, warm graph, fallback and CLI tests.
- [x] Compare full Windows test IDs/outcomes and line/branch coverage before and after.
- [x] Run complete hosted matrix and measure Windows pytest steps against the baseline.

The first hosted ABBA comparison did not establish an overall speedup. It exposed
30-second audit setup pauses. A nested pytest run with its own temporary directory
reduced that setup from 15.02s to 1.20s locally, retaining all 33 audit tests. The
final hosted comparison also gives each outer arm a fresh explicit temporary base
so one arm does not benchmark deletion of another arm's Git fixture trees.

Final matched run 39854060026 passed all eight complete suites. Python 3.11 mean
90.48s to 84.38s; Python 3.14 mean 123.43s to 128.01s, so no full-suite 3.14
improvement is claimed. All original test outcomes and covered unchanged source
lines/branches are preserved. See [the complete measurement report](../../benchmarks/windows-runtime.md).
