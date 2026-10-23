# Publishing pytest-selective

The distribution is `pytest-selective`; imports use `pytest_selective`.
The version has one source of truth: `[project].version` in `pyproject.toml`.

## One-time PyPI setup

The workflow uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
with GitHub OIDC, so no long-lived PyPI API token belongs in GitHub secrets.
A PyPI project owner must register this publisher (or a pending publisher for
the first release):

| Field | Value |
| --- | --- |
| PyPI project | `pytest-selective` |
| GitHub owner | `gigaverse-app` |
| Repository | `pytest-selective` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

Use [pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
if the project does not exist. This registration happens in the owner's PyPI
account; committing a workflow does not create that trust relationship.

Create the GitHub `pypi` environment and restrict it to release tags (`v*`). Add
required reviewers according to your maintainer policy. Only the publishing job
receives `id-token: write`; it downloads already-tested artifacts and does not
check out or build source with that permission.

## Prepare and publish

1. Update `pyproject.toml` and `CHANGELOG.md`, run `uv lock`, and open a PR.
2. Require green CI: hooks, Linux/Windows/macOS tests, minimum pytest, metadata,
   and isolated wheel/sdist installation. Review the uploaded evidence.
3. Merge the reviewed change. Create tag `v<version>` on that commit, such as
   `v0.1.0`, and publish its GitHub Release. Normal versions are regular releases;
   mark alpha, beta and release-candidate versions as prereleases.
4. `release.yml` verifies that the tag exactly matches the package version,
   reruns the reusable CI workflow on that revision, and publishes its tested
   wheel and sdist with attestations through the `pypi` environment.
5. Verify the package page and install the exact released version in a clean
   environment: `pip install 'pytest-selective==<version>'`. Check
   `pytest-selective --help` and run the tutorial using that installation.

After a normal release publishes successfully, the workflow advances the
compatible Actions tag (for example, `v0.1` for `v0.1.0`). Consumers can use
`@v0.1` to receive patch releases. Package requirements use compatible ranges
such as `pytest-selective>=0.1.0,<0.2.0`; lockfiles retain resolved versions and
artifact hashes. Prereleases do not advance the Actions tag.

Manual dispatch is available for a version-matching **tag**, not a branch. The
workflow intentionally does not skip existing uploads: investigate a partial
release instead of silently treating it as successful. Published versions are
immutable; fix release defects with a new version and document any yanked release.

## After the first release

Replace the README's provisional Git install command with
`pip install pytest-selective` for normal releases (use `--pre` only while
prereleases are the only available versions). Add a live
PyPI version badge linked to the project page once the package is available.
Keep the Git source-install alternative. Do not claim PyPI availability or show
a success badge before verifying the published artifact.
