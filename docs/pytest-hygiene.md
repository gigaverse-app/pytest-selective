# Keep pytest selection narrow

A new global fixture, plugin or application import can make a small change reach
every test. Selection should expose that cost before installing the application
or starting databases. pytest-selective includes two opt-in checks extracted from
backend-common; installing the package does not enable them automatically.

## Explain global expansion

Add `# gv:test-requires-expansion-reason` to a conftest you want to protect. The
historical marker remains supported so existing repositories need no rewrite.
Run the guard against the complete PR base, not an incremental test baseline:

```bash
pytest-selective-expansion --repo . --base origin/main --head HEAD \
  --module-root src --module-root . --project-import-prefix myapp
```

The command parses source without importing the application. New fixtures,
plugins, application imports and wider fixture scopes require a nearby reason:

```python
# gv:test-requires-expansion-reason
import pytest

# pytest-global: Every domain shares this clock; a local clock would disagree.
@pytest.fixture(scope="session")
def clock():
    return SharedClock()
```

Prefer a conftest at the narrowest consuming directory. A reason records an
intentional cost; it does not make a global dependency cheaper. Ordinary edits,
removals and moves retain their existing behavior. Invalid syntax or missing Git
history fail with an actionable error instead of approving an unexamined change.

The composite action is `.github/actions/pytest-expansion` in this repository.
Pin it to a reviewed commit. It uses the existing checkout and interpreter, with
no dependency install. Its `python-executable` input defaults to `python3.14`;
choose an interpreter at least as new as the inspected source syntax. The CLI
supports Python 3.11+ when the inspected syntax does too.

## Keep test modules independent

Importing one test module from another undermines file-level isolation. Put shared
fixtures and helpers in ordinary modules and enforce that boundary in a repo test:

```python
from pathlib import Path
from pytest_selective.hygiene import assert_test_file_isolation

def test_test_files_are_independent():
    assert_test_file_isolation(Path.cwd(), [Path("tests")])
```

The check follows Python import syntax and recognizes both `test_*.py` and
`*_test.py`. A helper inside a directory named `test_something` is still a helper;
directory names alone do not make it a test module.

CI-esta owns workflow evidence, cancellation, measurement and reporting. These
guards live here because they protect test-selection assumptions. See the
[CI adoption guide](ci.md) for complete-suite fallbacks and explicit full runs.
