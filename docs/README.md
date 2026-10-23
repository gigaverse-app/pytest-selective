# pytest-selective documentation

| Your goal | Start here |
| --- | --- |
| Have a coding agent optimize your test/CI workflow | [Agent prompt, skill and AGENTS.md instructions](agents.md) |
| See a real regression caught by a smaller selection | [Runnable tutorial](tutorial.md) |
| Configure an existing Python project | [Configuration and dependency declarations](configuration.md) |
| Use `pytest --selective` or run local edits before collection | [Native plugin and local runner](local-development.md) |
| Run the selected files safely in CI | [GitHub Actions and runner integration](ci.md) |
| Understand what has been demonstrated | [Evidence and limits](evidence.md) |
| Measure complete Windows suite runtime | [Windows runtime evidence](benchmarks/windows-runtime.md) |
| Improve the library | [Contributing](../CONTRIBUTING.md) |
| Publish a package | [Releasing](../RELEASING.md) |

Use `pytest-selective --help` for all CLI switches. The validated configuration
contract lives in [ImpactConfig](../src/pytest_selective/impact_models.py).
