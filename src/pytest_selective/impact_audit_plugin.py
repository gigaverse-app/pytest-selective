"""
Record which tracked repository files each test file reads, for ``gv-test-impact audit``.

Load it for one run from the command line or ``PYTEST_ADDOPTS``, never from pytest configuration:

    pytest -p pytest_selective.impact_audit_plugin --impact-audit-dir impact-audit

A consumer's pytest configuration naming ``backend_common`` stops first-party pin narrowing, and the
recorder cannot change a test's outcome, so it needs no graph edge. Every pytest process (each shard
and each xdist worker) writes one ``AuditRecord`` file into the directory at session end.

A read is an ``open`` audit event (``open``, ``Path.read_text``/``read_bytes`` and ``io.open_code``,
which imports and path-loaded modules use) or a subprocess argument naming a tracked file. It
belongs to the test file being collected or run at the time. Reads outside both, such as conftest
import or coverage reporting, belong to every test through the graph's conftest and global edges
and are not recorded. What a subprocess itself reads is out of reach: the script's own declarations
own those inputs.
"""

import os
import re
import shlex
import subprocess
import sys
import uuid
from collections.abc import Generator, Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path

import pytest

from pytest_selective.git_operations import git_text as _git
from pytest_selective.impact_models import AuditRecord

#: The positions of the program and its arguments in each process-launch audit event.
_COMMAND_ARGUMENTS = {
    "subprocess.Popen": (0, 1),
    "os.system": (0,),
    "os.exec": (0, 1),
    "os.posix_spawn": (0, 1),
    "os.spawn": (1, 2),
}
#: Git options before the subcommand whose value may be the next argument.
_GIT_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--attr-source"}
)
#: Splits shell command strings and ``--option=path`` arguments into candidate paths.
_WORD_SEPARATORS = re.compile(r"[\s=;|&<>()'\"]+")
#: Library code that reads the source of every module already imported in the process for its
#: own heuristics. What it reads depends on what earlier tests imported, never on the test.
#: Hypothesis seeds its generators with constants parsed from local modules (6.131+).
_PROCESS_WIDE_READERS = frozenset({"hypothesis.internal.constants_ast"})
#: Standard-library code that asks ``linecache`` for a source line only to show it: a rendered
#: traceback (also behind ``logging.exception``) and a displayed warning. Which file that is depends
#: on whose frame or warning it is, and a thread left running by an earlier test file logs its own
#: frames while a later one is current. The text shown never changes a test's outcome.
_SOURCE_DISPLAY = frozenset({"traceback", "warnings"})


def _key(path: str) -> str:
    """The comparable spelling of a path: absolute, normalized and, on Windows, case-folded."""
    return os.path.normcase(os.path.abspath(path))


def _write_only(mode: object, flags: object) -> bool:
    # Writing a tracked file is output, not input: the graph ignores write-only opens too.
    if isinstance(mode, str):
        return "+" not in mode and "r" not in mode and any(flag in mode for flag in "wax")
    return mode is None and isinstance(flags, int) and flags & 3 == os.O_WRONLY


def _read_by_process_wide_reader() -> bool:
    """
    Whether the open on the stack is library bookkeeping and no input of the current test.

    A direct ``linecache`` or ``inspect.getsource`` call by a test stays a read: only ``linecache``
    reached from source display is exempt.
    """
    frame = sys._getframe(1)
    through_linecache = False
    while frame is not None:
        name = frame.f_globals.get("__name__")
        if name in _PROCESS_WIDE_READERS or (through_linecache and name in _SOURCE_DISPLAY):
            return True
        through_linecache = through_linecache or name == "linecache"
        frame = frame.f_back
    return False


def _words(value: object) -> Iterable[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    for item in items:
        if not isinstance(item, (str, bytes, os.PathLike)):
            continue
        text = os.fsdecode(item)
        yield text
        yield from (word for word in _WORD_SEPARATORS.split(text) if word and word != text)


def _git_words(executable: object, argv: object) -> list[str] | None:
    """Return the decoded arguments of a direct git invocation."""
    if isinstance(argv, str) and os.name == "nt":
        # Popen's Windows audit event carries a command line, even for a list of arguments.
        # Accept only a lossless decoding of the form Python itself emits.
        try:
            words = [word.removeprefix('"').removesuffix('"') for word in shlex.split(argv, posix=False)]
        except ValueError:
            return None
        if subprocess.list2cmdline(words) != argv:
            return None
    elif isinstance(argv, (list, tuple)) and all(isinstance(arg, (str, bytes, os.PathLike)) for arg in argv):
        words = [os.fsdecode(arg) for arg in argv]
    else:
        return None
    if not words:
        return None
    program = os.fsdecode(executable) if isinstance(executable, (str, bytes, os.PathLike)) else words[0]
    if os.path.normcase(os.path.basename(program)) not in {"git", "git.exe"}:
        return None
    return words


def _git_candidates(words: list[str], directory: str | None, work_tree: str | None) -> Iterable[tuple[str, str | None]]:
    """
    Yield each candidate path of a git command with the directory git resolves it in.

    Git applies every ``-C`` in order, wherever it stands among the options before the subcommand,
    and resolves a relative work tree in the directory they select. From a directory outside the
    work tree it runs at the work tree's top.
    """
    yield words[0], directory
    index = 1
    while index < len(words) and words[index].startswith("-"):
        option, assigned, value = words[index].partition("=")
        index += 1
        if not assigned and option in _GIT_VALUE_OPTIONS and index < len(words):
            value = words[index]
            index += 1
        if option == "-C":
            yield value, directory
            if value:
                directory = os.path.realpath(os.path.join(directory or os.curdir, value))
            continue
        if option == "--work-tree":
            work_tree = value
        yield from ((word, directory) for word in _words(value) if word)
    if work_tree:
        current = os.path.realpath(directory or os.curdir)
        top = os.path.realpath(os.path.join(current, work_tree))
        try:
            inside = os.path.commonpath([top, current]) == top
        except ValueError:  # different drives
            inside = False
        if not inside:
            directory = top
    yield from ((word, directory) for word in _words(words[index:]))


def _environment_value(environment: object, name: str) -> str | None:
    """A variable of the environment a launched process receives; ``None`` inherits this process's."""
    if environment is None:
        return os.environ.get(name)
    if not isinstance(environment, Mapping):
        return None
    value = environment.get(name, environment.get(name.encode()))
    return os.fsdecode(value) if isinstance(value, (str, bytes, os.PathLike)) else None


class ReadRecorder:
    """Attributes tracked-file reads to the test file that is current when they happen."""

    def __init__(self, root: Path, tracked: Iterable[str]) -> None:
        # One dictionary lookup per event decides membership; nothing outside the repository matches.
        self._tracked = {_key(os.path.join(root, path)): path for path in tracked}
        self._owner: str | None = None
        self._inputs: dict[str, set[str]] = {}
        self._errors: set[str] = set()

    @contextmanager
    def attributed(self, path: Path) -> Generator[None]:
        """Attribute reads inside the block to ``path``; an untracked path records nothing."""
        previous = self._owner
        self._owner = self._tracked.get(_key(str(path)))
        try:
            yield
        finally:
            self._owner = previous

    def audit(self, event: str, args: tuple[object, ...]) -> None:
        """
        The ``sys.addaudithook`` callback.

        It runs for every audit event in the process, most of them never a read, so it returns
        before any work when no test is current. An exception raised here would propagate into
        the audited call and fail the test, so every failure is recorded instead.
        """
        owner = self._owner
        if owner is None:
            return
        try:
            if event == "open" and len(args) == 3:
                path, mode, flags = args
                if not _write_only(mode, flags):
                    self._add(owner, path, None)
            elif event in _COMMAND_ARGUMENTS:
                self._command(owner, event, args)
        except Exception as error:  # noqa: BLE001 - see the docstring
            self._errors.add(f"{event}: {error!r}")

    def _command(self, owner: str, event: str, args: tuple[object, ...]) -> None:
        cwd = args[2] if event == "subprocess.Popen" and len(args) > 2 else None
        directory = os.fsdecode(cwd) if isinstance(cwd, (str, bytes, os.PathLike)) else None
        for index in _COMMAND_ARGUMENTS[event]:
            if index < len(args):
                value = args[index]
                candidates: Iterable[tuple[str, str | None]] = ((word, directory) for word in _words(value))
                if index and (words := _git_words(args[index - 1], value)):
                    # Every process-launch event ends with the environment; None inherits this one.
                    environment = args[-1] if len(args) > index + 1 else None
                    candidates = _git_candidates(words, directory, _environment_value(environment, "GIT_WORK_TREE"))
                for word, where in candidates:
                    self._add(owner, word, where)

    def _add(self, owner: str, value: object, directory: str | None) -> None:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return
        text = os.fsdecode(value)
        relative = self._tracked.get(_key(os.path.join(directory, text) if directory else text))
        # The stack is inspected only for tracked files, a small fraction of all opens.
        if relative is not None and not _read_by_process_wide_reader():
            self._inputs.setdefault(owner, set()).add(relative)

    def record(self) -> AuditRecord:
        return AuditRecord(
            inputs={owner: sorted(paths) for owner, paths in sorted(self._inputs.items())},
            errors=sorted(self._errors),
        )


def tracked_files(root: Path) -> list[str]:
    return [path for path in _git(root, "ls-files", "-z").split("\0") if path]


def repository_root(start: Path) -> Path:
    return Path(_git(start, "rev-parse", "--show-toplevel").strip())


class ImpactAuditPlugin:
    """Sets the current test file around module collection and each test's run protocol."""

    def __init__(self, recorder: ReadRecorder, directory: Path) -> None:
        self._recorder = recorder
        self._directory = directory

    @pytest.hookimpl(wrapper=True)
    def pytest_make_collect_report(
        self, collector: pytest.Collector
    ) -> Generator[None, pytest.CollectReport, pytest.CollectReport]:
        # Importing a test module runs its module-level reads; only a Module collector imports one.
        if not isinstance(collector, pytest.Module):
            return (yield)
        with self._recorder.attributed(collector.path):
            return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item) -> Generator[None, object, object]:
        # Setup, call and teardown, including fixtures from conftests the graph already reaches.
        with self._recorder.attributed(item.path):
            return (yield)

    def pytest_sessionfinish(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        # One file per process: shards and xdist workers share the directory.
        record = self._directory / f"{uuid.uuid4().hex}.json"
        record.write_text(self._recorder.record().model_dump_json(), encoding="utf-8")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.getgroup("test impact").addoption(
        "--impact-audit-dir",
        dest="impact_audit_dir",
        default=None,
        help="Record the tracked files each test file reads into this directory, for gv-test-impact audit.",
    )


def pytest_configure(config: pytest.Config) -> None:
    directory = config.getoption("impact_audit_dir")
    if directory is None:
        return
    try:
        root = repository_root(config.invocation_params.dir)
        recorder = ReadRecorder(root, tracked_files(root))
    except (OSError, subprocess.CalledProcessError) as error:
        # A test that runs pytest in a temporary directory inherits the option through the
        # environment; the recorder must not change that nested run's outcome either.
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(f"impact audit disabled: no Git checkout to know tracked files ({error})"),
            stacklevel=2,
        )
        return
    # Tests may change directory; the record location is fixed at the invocation directory.
    output = Path(config.invocation_params.dir, directory).resolve()
    # An audit hook cannot be removed; it stays inert once no test file is current.
    sys.addaudithook(recorder.audit)
    config.pluginmanager.register(ImpactAuditPlugin(recorder, output), "gv-impact-audit")
