# Keep selection trustworthy and narrow

Test selection is useful when a small edit stays small and missing dependencies
are visible. Start with [local pytest](local-development.md) or [CI planning](ci.md),
then use these tools as your suite grows.

## Explain an unexpectedly large plan

```bash
pytest-selective affected --config .github/test-impact.json --base origin/main \
  --output selection.json --explanation-output explanation.json
pytest-selective explain --config .github/test-impact.json \
  --test tests/test_prices.py --source src/shop/prices.py
```

The explanation follows dependency paths and identifies global startup inputs.
A broad root conftest can make every test depend on a module. Move helpers and
fixtures to the narrowest consuming scope before accepting that cost. A configured
`floor_budget` can prevent accidental growth in the number of globally affected
files. The CI action checks that budget after publishing the explanation.

## Find runtime inputs missing from the model

```bash
uv add --dev 'pytest-selective[audit]'
uv run pytest -p pytest_selective.impact_audit_plugin --impact-audit-dir impact-audit
uv run pytest-selective audit --config .github/test-impact.json --records impact-audit
```

The recorder observes real file reads in the tests you execute. The audit can
expose a JSON fixture, template or schema that the graph did not declare. Add an
edge at the reader using a dependency comment or YAML sidecar, then recheck the
route. [Declaration syntax](configuration.md#declare-inputs-that-imports-cannot-describe).
The audit covers observed paths; keep representative full runs for paths it has
not seen, and explicitly model dynamic imports and external inputs.

## Prevent future broadening

Use the [expansion and isolation guards](pytest-hygiene.md). Protected conftests
require reasons for new global fixtures, plugins and imports. Test-file isolation
catches direct imports from one test module into another. These checks are opt-in;
installing the selector does not silently enforce a new policy.

Before changing the collection policy, review and refresh its fingerprints.
Unknown configuration makes the CI action fall back to the complete configured
roots. Invalid dependency declarations need correction. A selected green run is
not a claim that every test in the full suite would pass.
