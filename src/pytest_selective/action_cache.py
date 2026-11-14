"""GitHub transport keys for disposable analysis caches; stdlib bootstrap only."""

import hashlib
import os
import re
import subprocess
from pathlib import Path

from pytest_selective.git_operations import git_text


def _commit(repo: Path, revision: str) -> str | None:
    if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", revision):
        return revision.lower()
    if not revision:
        return None
    try:
        return git_text(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").strip()
    except subprocess.CalledProcessError:
        return None


def cache_keys(
    repo: Path, *, head: str, bases: list[str], ref: str, default_branch: str, os_name: str, run: str
) -> tuple[str, list[str]]:
    """Prefer the analyzed head, previous PR work, then the exact default-branch base.

    GitHub's ref-scoped access rules still apply. Keys are hints only: GraphCache
    validates content ids, parser versions, configuration and record checksums.
    The old OS-wide prefix remains last to seed migration from v1 caches.
    """
    revision = _commit(repo, head)
    if revision is None:
        raise ValueError(f"cannot resolve cache head {head!r}")
    prefix = f"test-impact-v2-{os_name}-py314-"
    current = prefix + hashlib.sha256(ref.encode()).hexdigest() + "-"
    default = prefix + hashlib.sha256(f"refs/heads/{default_branch}".encode()).hexdigest() + "-"
    commits = list(dict.fromkeys(commit for base in bases if (commit := _commit(repo, base))))
    exact = f"{current}{revision}-"
    legacy = f"test-impact-v1-{os_name}-"
    restores = [
        exact,
        *(f"{current}{commit}-" for commit in commits),
        current,
        *(f"{default}{commit}-" for commit in commits),
        *(f"{legacy}{commit}-" for commit in [revision, *commits]),
        default,
        legacy,
    ]
    return exact + run, list(dict.fromkeys(restores))


def main() -> None:
    key, restores = cache_keys(
        Path.cwd(),
        head=os.environ.get("IMPACT_HEAD", "HEAD"),
        bases=[os.environ.get(name, "") for name in ("IMPACT_BASE", "IMPACT_ALTERNATE_BASE", "IMPACT_GRAPH_BASE")],
        ref=os.environ["GITHUB_REF"],
        default_branch=os.environ["IMPACT_DEFAULT_BRANCH"],
        os_name=os.environ["RUNNER_OS"],
        run=f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}",
    )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"key={key}\nrestore-keys<<CACHE_KEYS\n" + "\n".join(restores) + "\nCACHE_KEYS\n")
    print("Graph cache lookup order:\n" + "\n".join(restores))


if __name__ == "__main__":
    main()
