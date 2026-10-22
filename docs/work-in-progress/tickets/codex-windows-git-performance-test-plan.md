# Windows Git performance verification

Keep the complete test inventory, OS/Python matrix, real Git histories, CLI journeys,
coverage collection, and conservative fallback behavior.

- [x] Record full native Windows baseline at a7be2f7 with the repaired coverage wheel metadata.
- [x] Exercise batched probes against real available, absent, duplicate and non-commit objects.
- [x] Run all existing dependency pin, bounded cache, warm graph, fallback and CLI tests.
- [x] Compare full Windows test IDs/outcomes and line/branch coverage before and after.
- [ ] Run complete hosted matrix and measure Windows pytest steps against the baseline.

The first hosted ABBA comparison did not establish an overall speedup. It exposed
30-second audit setup pauses. A nested pytest run with its own temporary directory
reduced that setup from 15.02s to 1.20s locally, retaining all 33 audit tests. The
final hosted comparison also gives each outer arm a fresh explicit temporary base
so one arm does not benchmark deletion of another arm's Git fixture trees.
