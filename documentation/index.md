---
title: pytest-selective documentation
description: Run affected Python tests safely, explain every selection, and skip unrelated CI lanes.
---

# pytest-selective

Run affected Python tests safely, explain every selection, and skip unrelated CI lanes.

[Get started](../docs/tutorial.md){ .md-button .md-button--primary }
[Source on GitHub](https://github.com/gigaverse-app/pytest-selective){ .md-button }

## Follow a measured example

[Skip unrelated CI jobs safely](../docs/tutorials/skip-unrelated-ci.md). Apply the steps to your own
repository, and inspect the original runs, retained checks, and measurement limits.

## Run the tests an edit can affect

Use affected-test selection for quick local feedback, or select complete CI
lanes when every test and validator in a contract must run together. Inspect the
explanation before relying on a skipped test. Keep full checkpoints and explicit
inputs for dependencies that Python imports cannot reveal.

- [Run the executable tutorial](../docs/tutorial.md): try selection in a small real Git repository.
- [Configure dependency inputs](../docs/configuration.md): declare collection policy and dynamic dependencies.
- [Select complete CI lanes](../docs/ci.md#select-whole-ci-lanes): avoid starting unrelated test infrastructure.
- [Improve local development](../docs/local-development.md): integrate selection into your pytest workflow.
- [Audit selection health](../docs/selection-health.md): investigate growing scope and fixture dependencies.
- [Read the evidence and limits](../docs/evidence.md): decide where selection is appropriate.

## Use the tools together

[Choose the tool for your problem](ecosystem.md). Each project works on its own;
combine them when you need both faster feedback and evidence that the required
work still happened.

## Versions and support

`latest` follows the main branch. Release-specific documentation is available
through Read the Docs when that release contains the site configuration.
Use [GitHub issues](https://github.com/gigaverse-app/pytest-selective/issues) for a minimal
reproducer or a missing explanation. [Contributions](../CONTRIBUTING.md) are welcome.
