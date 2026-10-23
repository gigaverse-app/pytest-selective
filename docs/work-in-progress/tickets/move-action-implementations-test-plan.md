# Move action implementations

Move implementations and helpers into actions/ and remove both generated named
wrapper layouts. Keep the root default entry point only. Older immutable releases
retain their original paths; callers upgrading must migrate path and revision together.

Validation covers complete input/output contracts, helper-file inventory, relative
script paths, receipt invalidation, GitHub API surface scans, installed distributions,
full Python suites, native Bun controls and hosted action smoke tests. Existing
required gates and platform coverage remain enabled.
