# Let your agent make pytest faster

Give your coding agent this prompt from the repository you want to improve:

```text
Read https://raw.githubusercontent.com/gigaverse-app/pytest-selective/main/skills/pytest-selective/SKILL.md
and use it to improve this repository's Python test/CI time. Choose file or
whole-lane selection to preserve our coverage and conformance requirements.
Add routing regressions, retain docs/package checks and full checkpoints,
and show measured before/after results with the assumptions and run links.
```

The [skill](../skills/pytest-selective/SKILL.md) is ordinary Markdown with standard
metadata. An agent with repository, Git and shell access can read it directly.
It can use connected CI tools or `gh` for live measurements; without CI access it
can still prepare the change and local routing evidence. No new agent service
or MCP server is required.

## Optional installation

With Node.js 22.20+ and the [open skills CLI](https://github.com/vercel-labs/skills),
run from your target project and choose your coding agent:

```bash
npx skills add gigaverse-app/pytest-selective --skill pytest-selective
npx skills add gigaverse-app/ci-esta --skill ci-esta
```

The second skill adds GitHub Actions reporting and optional evidence reuse for
any application language. It is optional for Python selection. Alternatively,
copy the complete `skills/pytest-selective/` folder into your agent's skill
directory; keep `references/` alongside `SKILL.md`. Review the source/revision
when installing or updating. The two projects' Git repositories are the source
of these skills; a Python wheel install is not an agent-skill installation.

For agents that read `AGENTS.md`, merge this small policy into your existing file:

```markdown
## Test/CI optimization
Use the pytest-selective skill when narrowing Python test execution.
Declare non-import inputs, prove routing with real Git changes, and retain
docs/package checks, required gates and full-suite checkpoints.
For GitHub Actions timing or repeated work, also use the CI-esta skill.
Report measured runner time and elapsed time separately, with run links.
```

## What to expect

The agent should leave a reviewable config/workflow change, consumer routing
tests, input assumptions and evidence. A README edit must not start databases
when it cannot affect runtime tests, but source, fixture, lock and execution
workflow edits must retain their affected coverage. If the repository cannot
safely use partial collection, keep complete lanes. If the measured benefit is
negligible, say so rather than adding selection machinery for its own sake.

Our own README scenario used **48 instead of 627 runner-seconds**, with elapsed
time dropping **211s to 26s**. That is one successful matched pair, not a promise
for your project. [Read the evidence](benchmarks/2026-10-22-routing.md).

## Keep installed skills current

The repository's `skills/` directory is the authoritative copy. A package upgrade
does not refresh an agent's installed Markdown. Reinstall/update with your skill
manager, or replace the complete skill folder (including `references/`) after
reviewing the source revision. Compare that revision when an agent gives advice
that conflicts with the current quickstart. Preserve local customizations separately.
