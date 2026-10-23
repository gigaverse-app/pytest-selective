# Shared public action directory

Keep the root default action; recommend `actions/NAME` for individual actions.
Preserve both existing named and `.github/actions/NAME` callers.

- [x] Verify every input/default/output and pinned delegation for new and existing paths.
- [x] Route changes to action metadata and helper files to the full test lane.
- [x] Include the shared directory in execution evidence and distribution inputs.
- [x] Validate updated workflows and examples with actionlint.
- [ ] Run hosted smoke tests through the new directory and pass normal CI.
