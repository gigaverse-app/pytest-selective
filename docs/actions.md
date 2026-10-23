# Public GitHub Actions

Use `gigaverse-app/pytest-selective@main` for test-impact. Specialized actions use
`gigaverse-app/pytest-selective/actions/ACTION@main`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

These public paths are new on main and are not present in older released tags.
Use a reviewed commit containing the root `action.yml`, or `@main` while evaluating.
After Release Please publishes this feature, use the corresponding compatible
release tag or an immutable commit SHA. Do not change an old version tag to make
new paths appear. Python package versions and installed agent skills are separate:
updating one does not update the others.

Each `actions/NAME` directory contains the implementation and its helper files.
The former `.github/actions/NAME` and top-level `NAME` directories have been
removed from main. Update the path and revision together when migrating:
`gigaverse-app/pytest-selective/actions/NAME@REVISION`. Old immutable releases keep their
original layouts; a new path cannot be used with a release that predates it.

The root default action delegates to its implementation at the **same pinned
revision**. Only this root entry point is generated; after changing the primary
action's inputs or outputs, run `uv run python scripts/public_actions.py`.

The root convenience action uses GitHub's self-repository reference (`$/`),
supported on GitHub.com with runner 2.336.0 or newer. Individual `actions/NAME`
entry points call the implementations directly and do not require that syntax.
[GitHub reference documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Action reference

Each link below is the public action's complete input/output contract.

| Entry point | Contract |
| --- | --- |
| `gigaverse-app/pytest-selective@main` | [Root action](../action.yml) |
| `gigaverse-app/pytest-selective/actions/plan-lanes@main` | [plan-lanes](../actions/plan-lanes/action.yml) |
| `gigaverse-app/pytest-selective/actions/pytest-expansion@main` | [pytest-expansion](../actions/pytest-expansion/action.yml) |
| `gigaverse-app/pytest-selective/actions/test-impact@main` | [test-impact](../actions/test-impact/action.yml) |

Reusable workflows are a different interface: GitHub requires them to live under
`.github/workflows/` and callers use `jobs.<job>.uses`. Actions use
`jobs.<job>.steps[].uses`. The root action is for a step, not a replacement for a
reusable workflow at job level.
