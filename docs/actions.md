# Public GitHub Actions

Use `gigaverse-app/pytest-selective@main` for test-impact. Specialized actions use
`gigaverse-app/pytest-selective/ACTION@main`. Your workflow does not need a checkout of
this toolkit or a Python package installation to load an action. Actions that
analyze your project still need your project's checkout.

## Availability and pinning

These public paths are new on main and are not present in older released tags.
Use a reviewed commit containing the root `action.yml`, or `@main` while evaluating.
After Release Please publishes this feature, use the corresponding compatible
release tag or an immutable commit SHA. Do not change an old version tag to make
new paths appear. Python package versions and installed agent skills are separate:
updating one does not update the others.

Existing `.github/actions/NAME` paths continue to work with the same inputs,
outputs and defaults. Public entry points delegate to those implementations at
the **same pinned revision**; no second implementation or floating nested pin is
involved. Maintainers regenerate metadata with
`uv run python scripts/public_actions.py`; CI checks the forwarding contracts.

Public wrappers use GitHub's self-repository reference (`$/`), supported on
GitHub.com with runner 2.336.0 or newer. For older self-hosted runners or GitHub
Enterprise Server without that syntax, retain the compatibility paths and their
existing version pins. [GitHub reference documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Action reference

Each link below is the public action's complete input/output contract.

| Entry point | Contract |
| --- | --- |
| `gigaverse-app/pytest-selective@main` | [Root action](../action.yml) |
| `gigaverse-app/pytest-selective/plan-lanes@main` | [plan-lanes](../plan-lanes/action.yml) |
| `gigaverse-app/pytest-selective/pytest-expansion@main` | [pytest-expansion](../pytest-expansion/action.yml) |
| `gigaverse-app/pytest-selective/test-impact@main` | [test-impact](../test-impact/action.yml) |

Reusable workflows are a different interface: GitHub requires them to live under
`.github/workflows/` and callers use `jobs.<job>.uses`. Actions use
`jobs.<job>.steps[].uses`. The root action is for a step, not a replacement for a
reusable workflow at job level.
