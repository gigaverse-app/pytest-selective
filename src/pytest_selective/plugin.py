"""Opt-in pytest integration over the same planner used by the CLI and CI."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest


@dataclass
class Selection:
    known: set[Path] = field(default_factory=set)
    selected: set[Path] = field(default_factory=set)
    message: str = ""
    deselected: int = 0


_selection = pytest.StashKey[Selection]()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("selective", "Git-based affected test selection")
    group.addoption("--selective", action="store_true", default=None, help="Run tests affected by local Git changes.")
    group.addoption("--no-selective", action="store_true", help="Disable selection, including configuration defaults.")
    group.addoption("--selective-config", metavar="PATH", help="ImpactConfig JSON path, relative to pytest rootdir.")
    group.addoption(
        "--selective-base", metavar="REF", help="Compare the working tree against this Git ref (default HEAD)."
    )
    parser.addini("selective", "Enable affected test selection", type="bool", default=False)
    parser.addini("selective_config", "ImpactConfig JSON path, relative to pytest rootdir", default="")
    parser.addini("selective_base", "Git comparison ref", default="HEAD")


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("no_selective") or not (config.getoption("selective") or config.getini("selective")):
        return
    if hasattr(config, "workerinput"):
        plan = config.workerinput["pytest_selective"]
        config.stash[_selection] = Selection(
            known={Path(p) for p in plan["known"]},
            selected={Path(p) for p in plan["selected"]},
            message=plan["message"],
        )
        return
    config.stash[_selection] = _plan(config)


def _plan(config: pytest.Config) -> Selection:
    # Loading the plugin must not load the graph machinery or invoke Git unless enabled.
    import os

    from pydantic import ValidationError

    from pytest_selective.impact_graph import (
        DependencyDeclarationError,
        GraphCache,
        git,
        inventory,
        policy_fingerprints,
    )
    from pytest_selective.impact_models import ImpactConfig
    from pytest_selective.impact_selection import affected
    from pytest_selective.working_tree import snapshot_working_tree

    path = config.getoption("selective_config") or config.getini("selective_config")
    config_path = (config.rootpath / path).resolve() if path else None
    policy = None
    if config_path:
        try:
            policy = ImpactConfig.model_validate_json(config_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise pytest.UsageError(f"Invalid selective configuration: {error}") from error
    cache = None
    try:
        repo = Path(git(config.rootpath, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        head = snapshot_working_tree(repo)
        tree = inventory(repo, head)
        fingerprints = policy_fingerprints(repo, tree)
        extra_config: list[str] = []
        if config.inipath is not None:
            ini = config.inipath.resolve()
            if not ini.is_relative_to(repo):
                raise ValueError("pytest configuration is outside the Git repository")
            ini_path = ini.relative_to(repo).as_posix()
            if ini_path not in fingerprints:
                extra_config = [ini_path]
        if policy is None:
            policy = ImpactConfig(
                module_roots=(["src"] if (repo / "src").is_dir() else []) + ["."],
                test_roots=["."],
                test_patterns=config.getini("python_files"),
                # Native pytest has already established collection policy. The
                # base must have the same fingerprint or the planner runs full.
                pytest_config_files=extra_config,
                pytest_policy=policy_fingerprints(repo, tree, tuple(extra_config)),
            )
        elif extra_config:
            # An explicit JSON policy must review nonstandard -c files too.
            policy.pytest_config_files = sorted(set(policy.pytest_config_files + extra_config))
        cache_path = git(repo, "rev-parse", "--git-path", "pytest-selective/cache.sqlite3").decode().strip()
        cache = GraphCache(repo / cache_path)
        report = affected(
            repo,
            config.getoption("selective_base") or config.getini("selective_base"),
            head,
            policy,
            cache,
            config_path=config_path.relative_to(repo).as_posix()
            if config_path is not None and config_path.is_relative_to(repo)
            else None,
            dependency_token=os.environ.get("IMPACT_DEPENDENCY_TOKEN") or None,
        )
        message = f"{report.mode}: {len(report.selected)}/{report.total_files} test files; " + "; ".join(report.reasons)
        if report.mode == "full":
            return Selection(message=message)
        return Selection(
            known={(repo / p).resolve() for p in cache.snapshot(repo, head, policy).tests},
            selected={(repo / p).resolve() for p in report.selected},
            message=message,
        )
    except DependencyDeclarationError as error:
        raise pytest.UsageError(f"Invalid test dependency: {error}") from error
    except Exception as error:
        # A warning filter must never turn a safe full run into an error.
        return Selection(message=f"full-suite fallback: {error}")
    finally:
        if cache is not None:
            cache.close()


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node) -> None:
    state = node.config.stash.get(_selection, None)
    if state is not None:
        node.workerinput["pytest_selective"] = {
            "known": sorted(map(str, state.known)),
            "selected": sorted(map(str, state.selected)),
            "message": state.message,
        }


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    state = config.stash.get(_selection, None)
    if state is None or not state.known:
        return
    kept, removed = [], []
    for item in items:
        # Unknown collectors, doctests, and files outside the graph remain runnable.
        # Collection path matters for inherited tests and generated BDD functions.
        path = item.path.resolve()
        definition = (config.rootpath / item.location[0]).resolve()
        if (
            not isinstance(item, pytest.Function)
            or path not in state.known
            or path in state.selected
            or definition in state.selected
        ):
            kept.append(item)
        else:
            removed.append(item)
    if removed:
        state.deselected += len(removed)
        config.hook.pytest_deselected(items=removed)
        items[:] = kept


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    state = session.config.stash.get(_selection, None)
    if state is None:
        return
    if hasattr(session.config, "workeroutput"):
        session.config.workeroutput["selective_deselected"] = state.deselected
    # Only selection-caused emptiness is successful. Preserve -k/-m emptiness,
    # missing node IDs, collection errors, interrupts, failures, and empty suites.
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED and state.deselected:
        session.exitstatus = pytest.ExitCode.OK


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error) -> None:
    state = node.config.stash.get(_selection, None)
    if state is not None:
        state.deselected += node.workeroutput.get("selective_deselected", 0)


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    state = config.stash.get(_selection, None)
    if state is not None:
        terminalreporter.write_line(f"pytest-selective: {state.message}")
