import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from pytest_selective.impact_audit import audit, load_records, summary
from pytest_selective.impact_audit_plugin import ReadRecorder
from pytest_selective.impact_cli import main
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import (
    AuditExemption,
    AuditRecord,
    AuditReport,
    ImpactConfig,
    UndeclaredRead,
)
from tests.testing.git_repo import commit, write

PLUGIN = "pytest_selective.impact_audit_plugin"
EXIT_UNDECLARED = 2
EXIT_OPERATIONAL = 1
TEST = "tests/test_reader.py"
DATA = "data/value.txt"

# One repository exercising every way a test reaches a file, declared or not.
READERS = {
    "src/pkg/__init__.py": "",
    "src/pkg/loader.py": (
        "# gv:test-dependency: data/declared.json\n"
        "from pathlib import Path\n"
        "def declared(): return Path('data/declared.json').read_text()\n"
        "def hidden(): return Path('data/hidden.json').read_text()\n"
    ),
    "tests/conftest.py": (
        "# gv:test-dependency: data/fixture.txt\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture\n"
        "def fixture_text(): return Path('data/fixture.txt').read_text()\n"
    ),
    "tests/test_module_level.py": (
        "from pathlib import Path\nDATA = Path('data/module_level.txt').read_text()\ndef test_data(): assert DATA\n"
    ),
    "tests/test_helper.py": (
        "from pkg.loader import declared, hidden\n"
        "def test_declared(): assert declared()\n"
        "def test_hidden(): assert hidden()\n"
    ),
    "tests/test_content.py": "from pathlib import Path\ndef test_text(): assert Path('data/content.txt').read_text()\n",
    "tests/test_content.py.gv-dependency.yaml": "dependencies:\n  - inputs: ['//data/content.txt']\n    kind: content\n",
    "tests/test_subprocess.py": (
        "import subprocess, sys\ndef test_script(): subprocess.run([sys.executable, 'scripts/tool.py'], check=True)\n"
    ),
    "tests/test_fixture.py": "def test_fixture(fixture_text): assert fixture_text\n",
    "tests/test_outputs.py": (
        "from pathlib import Path\n"
        "def test_outputs(tmp_path):\n"
        "    (tmp_path / 'scratch.txt').write_text('x')\n"
        "    assert (tmp_path / 'scratch.txt').read_text()\n"
        "    with open('data/written.txt', 'a') as output: output.write('x')\n"
    ),
    "tests/test_exempt.py": "from pathlib import Path\ndef test_exempt(): assert Path('data/exempt.txt').read_text()\n",
    "scripts/tool.py": "print('ok')\n",
    **{f"data/{name}": "1" for name in ["declared.json", "hidden.json", "fixture.txt", "module_level.txt"]},
    **{f"data/{name}": "1" for name in ["content.txt", "written.txt", "exempt.txt"]},
}
UNDECLARED = [
    UndeclaredRead(test="tests/test_exempt.py", input="data/exempt.txt"),
    UndeclaredRead(test="tests/test_helper.py", input="data/hidden.json"),
    UndeclaredRead(test="tests/test_module_level.py", input="data/module_level.txt"),
    UndeclaredRead(test="tests/test_subprocess.py", input="scripts/tool.py"),
]
EXEMPTION = AuditExemption(readers=["tests/test_exempt.py"], inputs=["data/exempt.txt"], reason="Covered elsewhere")


class AuditedRun(BaseModel):
    repo: Path
    records: Path


def run_audited_pytest(repo: Path, records: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(repo / "src"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    # An explicit empty ini outside the repository: no ancestor configuration of the temporary
    # directory can redirect collection, and the committed tree carries no pytest policy.
    isolated = repo.parent / "isolated-pytest.ini"
    isolated.write_text("[pytest]\n", encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-c",
            str(isolated),
            "--rootdir",
            str(repo),
            "-p",
            PLUGIN,
            "--impact-audit-dir",
            str(records),
            *args,
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def audited_run(tmp_path_factory: pytest.TempPathFactory) -> AuditedRun:
    """The fixture repository's suite, run once under the recorder with a relative record directory."""
    repo = tmp_path_factory.mktemp("audited") / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for path, content in READERS.items():
        write(repo, path, content)
    commit(repo)
    result = run_audited_pytest(repo, Path("audit-records"), "tests")
    assert result.returncode == 0, result.stdout + result.stderr
    return AuditedRun(repo=repo, records=repo / "audit-records")


def audit_cli(run: AuditedRun, tmp_path: Path, config: ImpactConfig, *args: str) -> int:
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    return main(
        [
            "audit",
            "--repo",
            str(run.repo),
            "--config",
            str(config_path),
            "--cache",
            str(tmp_path / "cache.sqlite3"),
            "--records",
            str(run.records),
            *args,
        ]
    )


def repo_config(*exemptions: AuditExemption) -> ImpactConfig:
    return ImpactConfig(module_roots=["src", "."], test_roots=["tests"], audit_exemptions=list(exemptions))


def test_audit_fails_on_exactly_the_reads_the_graph_cannot_reach(
    audited_run: AuditedRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    INVARIANT: a recorded read fails the audit iff the reading test's closure lacks the input.

    Inline, conftest and content-sidecar declarations reach their inputs; module-level reads,
    helper reads and executed scripts without one do not. Temporary files and write-only opens
    of tracked files are never inputs.
    """
    report_path = tmp_path / "report.json"
    summary_path = tmp_path / "summary.md"
    exit_code = audit_cli(
        audited_run, tmp_path, repo_config(), "--output", str(report_path), "--summary", str(summary_path)
    )
    report = AuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert exit_code == EXIT_UNDECLARED
    assert report.undeclared == UNDECLARED
    assert report.recorder_errors == []
    assert "data/written.txt" not in report_path.read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert all(f"{read.test} -> {read.input}" in printed for read in UNDECLARED)
    assert all(f"| `{read.test}` | `{read.input}` |" in summary_path.read_text() for read in UNDECLARED)


def test_exemption_accepts_only_its_own_reader_and_input(audited_run: AuditedRun, tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    exit_code = audit_cli(audited_run, tmp_path, repo_config(EXEMPTION), "--output", str(report_path))
    report = AuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert exit_code == EXIT_UNDECLARED
    assert report.undeclared == UNDECLARED[1:]
    assert report.exempted_reads == 1


def test_always_run_tests_cannot_miss_an_input(audited_run: AuditedRun, tmp_path: Path) -> None:
    """Every change selects an always-run test, so its reads need no edge."""
    report_path = tmp_path / "report.json"
    config = repo_config().model_copy(update={"always_run": ["tests/test_exempt.py"]})
    audit_cli(audited_run, tmp_path, config, "--output", str(report_path))
    report = AuditReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.undeclared == UNDECLARED[1:]
    assert report.exempted_reads == 1


def test_fully_declared_run_passes(audited_run: AuditedRun, tmp_path: Path) -> None:
    config = repo_config(
        AuditExemption(readers=["tests/*.py"], inputs=["data/*", "scripts/tool.py"], reason="Covered elsewhere")
    )
    assert audit_cli(audited_run, tmp_path, config) == 0


@pytest.mark.parametrize("stale", ["readers", "inputs"])
def test_stale_exemption_is_an_authoring_error(
    audited_run: AuditedRun, tmp_path: Path, capsys: pytest.CaptureFixture[str], stale: str
) -> None:
    exemption = EXEMPTION.model_copy(update={stale: ["renamed/*.txt"]})
    assert audit_cli(audited_run, tmp_path, repo_config(exemption)) == EXIT_UNDECLARED
    assert "audit_exemptions[0]" in capsys.readouterr().err


def test_missing_records_prove_nothing(audited_run: AuditedRun, tmp_path: Path) -> None:
    empty = AuditedRun(repo=audited_run.repo, records=tmp_path / "no-records")
    empty.records.mkdir()
    assert audit_cli(empty, tmp_path, repo_config()) == EXIT_OPERATIONAL


def test_records_from_every_process_are_unioned(audited_run: AuditedRun, tmp_path: Path) -> None:
    """Shards and xdist workers each write a record; one shard's reads never hide another's."""
    records = tmp_path / "records"
    for test in ["tests/test_module_level.py", "tests/test_helper.py"]:
        assert run_audited_pytest(audited_run.repo, records, test).returncode == 0
    run = AuditedRun(repo=audited_run.repo, records=records)
    snapshot = GraphCache(tmp_path / "cache.sqlite3").snapshot(run.repo, "HEAD", repo_config())
    report = audit(snapshot, load_records(records), repo_config())
    assert report.records == 2
    assert report.undeclared == [UNDECLARED[1], UNDECLARED[2]]


def test_editing_exemptions_reuses_the_resolved_graph(audited_run: AuditedRun, tmp_path: Path) -> None:
    cache = GraphCache(tmp_path / "cache.sqlite3")
    cache.snapshot(audited_run.repo, "HEAD", repo_config())
    cache.snapshot(audited_run.repo, "HEAD", repo_config(EXEMPTION))
    assert cache.snapshot_hits == 1
    cache.close()


def test_summary_without_findings_has_no_table() -> None:
    report = AuditReport(
        head="tree",
        records=1,
        audited_tests=1,
        recorded_reads=1,
        exempted_reads=0,
        undeclared=[],
        recorder_errors=["open: boom"],
    )
    text = summary(report)
    assert "| Test file |" not in text
    assert "- `open: boom`" in text


@pytest.fixture
def recorder(tmp_path: Path) -> ReadRecorder:
    write(tmp_path, DATA, "1")
    write(tmp_path, TEST)
    return ReadRecorder(tmp_path, [DATA, TEST])


def recorded(recorder: ReadRecorder, root: Path, event: str, *args: object) -> AuditRecord:
    with recorder.attributed(root / TEST):
        recorder.audit(event, args)
    return recorder.record()


@pytest.mark.parametrize(
    ("mode", "flags", "read"),
    [
        ("r", 0, True),
        ("rb", 0, True),
        ("w", 0, False),
        ("a", 0, False),
        ("r+", 0, True),
        ("w+", 0, True),
        (None, os.O_RDONLY, True),
        (None, os.O_WRONLY | os.O_CREAT, False),
        (None, os.O_RDWR, True),
    ],
)
def test_open_records_reads_but_not_write_only_opens(
    recorder: ReadRecorder, tmp_path: Path, mode: str | None, flags: int, read: bool
) -> None:
    record = recorded(recorder, tmp_path, "open", tmp_path / DATA, mode, flags)
    assert record.inputs == ({TEST: [DATA]} if read else {})


@pytest.mark.parametrize(
    ("event", "args"),
    [
        ("subprocess.Popen", ("python", ["python", DATA], None, None)),
        ("subprocess.Popen", (None, f"python {DATA} --flag", None, None)),
        ("subprocess.Popen", (None, ["python", f"--input={DATA}"], None, None)),
        ("subprocess.Popen", (None, ["python", Path(DATA).name], "data", None)),
        ("os.system", (f"cat '{DATA}' | wc",)),
        ("os.posix_spawn", ("python", [b"python", DATA.encode()], {})),
        ("os.spawn", (0, "python", ["python", DATA], {})),
    ],
)
def test_subprocess_arguments_naming_tracked_files_are_reads(
    recorder: ReadRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str, args: tuple[object, ...]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert recorded(recorder, tmp_path, event, *args).inputs == {TEST: [DATA]}


@pytest.mark.parametrize(
    "args",
    [
        (3, "r", 0),  # a file descriptor names no path
        ("outside.txt", "r", 0),
        ("data", "r", 0),  # directories are never inputs
    ],
)
def test_opens_outside_tracked_files_are_ignored(
    recorder: ReadRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: tuple[object, ...]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert recorded(recorder, tmp_path, "open", *args).inputs == {}


def test_reads_outside_a_test_or_by_an_untracked_test_are_not_recorded(recorder: ReadRecorder, tmp_path: Path) -> None:
    recorder.audit("open", (str(tmp_path / DATA), "r", 0))
    with recorder.attributed(tmp_path / "tests" / "generated_test.py"):
        recorder.audit("open", (str(tmp_path / DATA), "r", 0))
    assert recorder.record() == AuditRecord()


HYPOTHESIS_CONSTANTS = "hypothesis.internal.constants_ast"


def test_hypothesis_constant_collection_is_not_a_test_input(recorder: ReadRecorder, tmp_path: Path) -> None:
    """Hypothesis parses every imported local module for constants: what it reads is process history."""
    namespace: dict[str, object] = {"__name__": HYPOTHESIS_CONSTANTS}
    exec("def read(recorder, path):\n    recorder.audit('open', (path, 'rb', 0))\n", namespace)
    read = namespace["read"]
    assert callable(read)
    with recorder.attributed(tmp_path / TEST):
        read(recorder, str(tmp_path / DATA))
    assert recorder.record() == AuditRecord()


class BrokenPath(os.PathLike[str]):
    def __fspath__(self) -> str:
        raise RuntimeError("unreadable path")


def test_recorder_failure_is_reported_and_never_raised_into_the_test(recorder: ReadRecorder, tmp_path: Path) -> None:
    record = recorded(recorder, tmp_path, "open", BrokenPath(), "r", 0)
    assert record.inputs == {}
    assert record.errors == ["open: RuntimeError('unreadable path')"]


def test_outside_a_git_checkout_the_recorder_warns_and_never_changes_the_outcome(tmp_path: Path) -> None:
    """A test running pytest in a temporary directory inherits the recorder option."""
    write(tmp_path, "test_plain.py", "def test_plain(): pass\n")
    result = run_audited_pytest(tmp_path, tmp_path / "records", "test_plain.py")
    assert result.returncode == pytest.ExitCode.OK, result.stdout + result.stderr
    assert "impact audit disabled" in result.stdout
    assert not (tmp_path / "records").exists()
