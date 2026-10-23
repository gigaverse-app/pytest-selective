# pytest-selective actions

Use `gigaverse-app/pytest-selective/actions/NAME@REF` for individual actions, such as
`gigaverse-app/pytest-selective/actions/plan-lanes@main`.
The root `gigaverse-app/pytest-selective@REF` action plans affected test files.

See the [action reference and version availability](../docs/actions.md) for
inputs, outputs and compatible pins, or start with the
[complete CI recipe](../docs/ci.md).

Each directory contains the actual implementation and its helpers. Only the
root default action is generated; refresh it with
`uv run python scripts/public_actions.py` after changing test-impact's metadata.
