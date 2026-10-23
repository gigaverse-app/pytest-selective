# pytest-selective actions

Use `gigaverse-app/pytest-selective/actions/NAME@REF` for individual actions, such as
`gigaverse-app/pytest-selective/actions/plan-lanes@main`.
The root `gigaverse-app/pytest-selective@REF` action plans affected test files.

See the [action reference and version availability](../docs/actions.md) for
inputs, outputs and compatible pins, or start with the
[complete CI recipe](../docs/ci.md).

These entry points are generated from the canonical implementations in
`.github/actions/`. Run `uv run python scripts/public_actions.py` after changing
an action's metadata. Existing top-level named paths remain compatibility aliases.
