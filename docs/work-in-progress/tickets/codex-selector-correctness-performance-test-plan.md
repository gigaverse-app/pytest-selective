# Selector correctness and performance

- [x] Reproduce missing plugin edges with real Git history and actual pytest:
  changing a plugin dependency fails both tests, but selection returns no files.
- [x] Follow static plugin declarations recursively, with session-wide effects.
  Cover test-module registration, undotted/comma names, removal, unrelated code,
  nested plugins, and conservative handling of computed declarations.
- [x] Compare Rust import extraction with complete parsing on the frozen backend
  tree; preserve encoding errors and dependency declarations.
- [x] Measure cold, warm, and incremental graph creation. Improve the measured
  bottlenecks and verify identical graphs for behavior-preserving changes.
- [x] Run focused regressions and isolated wheel/sdist smoke checks on Python
  3.11 and 3.14, including worker parsing and real selection.
- [ ] Complete full local and hosted CI checks, release the package, and verify
  adopter CLI entry points. Consumer upgrades are coordinated with the existing
  CI-esta reporting task to avoid competing lockfile edits.
