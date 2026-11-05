# Retire the remaining duplication baseline

Preserve the nine-pair baseline history while consolidating the seven remaining
pairs. Keep the expansion guard's standalone stdlib entry point and the planner's
conservative fallback behavior.

- [ ] Git repository isolation: extend the real two-repository portability case
  through audit discovery; inherited hook variables must not select another repo.
- [ ] Root type-check inclusion: exercise committed base/head changes with omitted,
  dot and trailing-slash root includes; affected importers must still be checked.
- [ ] Test inventory: cached test copies must not create isolation findings; a real
  importing test remains the positive control.
- [ ] Shared Git execution: retain binary input/output, explicit temporary indexes,
  UTF-8 text and caller-specific failure behavior through existing real Git tests.
- [ ] Module naming: retain source-root stripping, package initializers, root order,
  case normalization and standalone expansion checks through existing entry points.
- [ ] Full suite and real strict dry-lint sweep, generated ratchet, and unchanged
  second update; no added exclusions or baseline allowances.
