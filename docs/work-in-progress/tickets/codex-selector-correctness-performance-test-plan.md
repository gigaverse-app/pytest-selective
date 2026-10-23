# Selector correctness and performance

- [x] Reproduce missing plugin edges with real Git history and actual pytest:
  changing a plugin dependency fails both tests, but selection returns no files.
- [ ] Follow static plugin declarations recursively, with session-wide effects.
  Cover test-module registration, undotted/comma names, removal, unrelated code,
  nested plugins, and conservative handling of computed declarations.
- [ ] Compare Rust import extraction with complete parsing on the frozen backend
  tree; preserve encoding errors and dependency declarations.
- [ ] Measure cold, warm, and incremental graph creation. Improve the measured
  bottlenecks and verify identical graphs for behavior-preserving changes.
- [ ] Run focused regressions, full local checks and hosted CI. Exercise real
  adopter CLI entry points and record exact revisions and remaining limitations.
