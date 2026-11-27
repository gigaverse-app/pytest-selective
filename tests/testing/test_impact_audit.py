import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from pytest_selective.impact_audit import audit, load_records, summary
from pytest_selective.impact_audit_declarations import IMPORT_REASON
from pytest_selective.impact_audit_plugin import ReadRecorder
from pytest_selective.impact_cli import _workflow_value, main
from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import (
    AuditExemption,
    AuditRecord,
    AuditReport,
    ImpactConfig,
    UndeclaredRead,
)
from tests.testing.git_repo import commit, init, write

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
        "def hidden(): return Path('data', 'hidden.json').read_text()\n"
    ),
    "tests/conftest.py": (
        "# gv:test-dependency: data/fixture.txt\n"
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.fixture\n"
        "def fixture_text(): return Path('data/fixture.txt').read_text()\n"
    ),
    "tests/test_module_level.py": (
        "from pathlib import Path\nDATA = Path('data', 'module_level.txt').read_text()\ndef test_data(): assert DATA\n"
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
    "tests/test_exempt.py": "from pathlib import Path\ndef test_exempt(): assert Path('data', 'exempt.txt').read_text()\n",
    # A literal tracked path is a graph edge, so this read needs no declaration.
    "tests/test_literal.py": "from pathlib import Path\ndef test_literal(): assert Path('data/literal.txt').read_text()\n",
    "scripts/tool.py": "print('ok')\n",
    **{f"data/{name}": "1" for name in ["declared.json", "hidden.json", "fixture.txt", "module_level.txt"]},
    **{f"data/{name}": "1" for name in ["content.txt", "written.txt", "exempt.txt", "literal.txt"]},
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
            # This nested run owns its temporary files. The global pytest temp
            # root contains other tests' Git object stores, whose retention cleanup
            # is expensive on Windows and unrelated to recorder behavior.
            "--basetemp",
            str(repo / ".audit-pytest-tmp"),
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
    init(repo)
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

    Inline, conftest and content-sidecar declarations and literal tracked paths reach their inputs;
    module-level and helper reads of computed paths, and executed scripts, without a declaration do not. Temporary files and write-only opens
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


def test_written_declarations_leave_no_undeclared_read(
    audited_run: AuditedRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    INVARIANT: after --write-declarations, the audit of the working tree finds no undeclared read.

    The executed script becomes an `import` rule (the script's own imports are dependencies too);
    data files become `content` rules. Tests without undeclared reads get no sidecar.
    """
    repo = tmp_path / "repo"
    shutil.copytree(audited_run.repo, repo, ignore=shutil.ignore_patterns(".audit-pytest-tmp", "audit-records"))
    run = AuditedRun(repo=repo, records=audited_run.records)
    assert audit_cli(run, tmp_path, repo_config(), "--write-declarations") == 0
    written = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*.gv-dependency.yaml"))
    assert written == sorted(
        {f"{read.test}.gv-dependency.yaml" for read in UNDECLARED} | {"tests/test_content.py.gv-dependency.yaml"}
    )
    assert (repo / "tests/test_subprocess.py.gv-dependency.yaml").read_text(encoding="utf-8") == (
        "dependencies:\n"
        "  - inputs:\n"
        '      - "//scripts/tool.py"\n'
        "    kind: import\n"
        f"    reason: {json.dumps(IMPORT_REASON)}\n"
    )
    assert "kind: content" in (repo / "tests/test_helper.py.gv-dependency.yaml").read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    # Each sidecar says how many tests its inputs select, before anyone commits it.
    assert re.search(
        r"wrote tests/test_subprocess\.py\.gv-dependency\.yaml \(a change to these inputs selects \d+ of \d+ tests\)\n"
        r"  import: //scripts/tool\.py",
        printed,
    )
    assert f"Declared {len(UNDECLARED)} of {len(UNDECLARED)} undeclared reads" in printed
    # Several sidecars written into one directory point at a single shared manifest instead.
    assert re.search(r"hint: wrote \d+ sidecars in tests/; .* tests/\.gv-dependencies\.yaml", printed)
    assert audit_cli(run, tmp_path, repo_config(), "--working-tree") == 0


def copied_run(audited_run: AuditedRun, tmp_path: Path) -> AuditedRun:
    """A private copy of the audited repository, so a test can add declarations to it."""
    repo = tmp_path / "repo"
    shutil.copytree(audited_run.repo, repo, ignore=shutil.ignore_patterns(".audit-pytest-tmp", "audit-records"))
    return AuditedRun(repo=repo, records=audited_run.records)


PROPOSAL = re.compile(r"^(Create|Append to) (\S+):\n((?:.+\n)+)", re.M)


def test_applying_the_printed_declarations_passes_the_audit(
    audited_run: AuditedRun, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    INVARIANT: a failing audit prints, for every reading test, the sidecar text that declares its reads.

    Pasting exactly what the log shows, without running anything else, leaves no undeclared read, and the
    step summary proposes the same text. A test that already has a sidecar is told to append the rules.
    """
    run = copied_run(audited_run, tmp_path)
    existing = f"{UNDECLARED[1].test}.gv-dependency.yaml"
    write(
        run.repo,
        existing,
        'dependencies:\n  - inputs:\n      - "//data/declared.json"\n    kind: content\n    reason: "Fixture."\n',
    )
    commit(run.repo)
    summary_path = tmp_path / "summary.md"
    assert audit_cli(run, tmp_path, repo_config(), "--summary", str(summary_path)) == EXIT_UNDECLARED
    printed = capsys.readouterr().out
    proposals = PROPOSAL.findall(printed)
    assert sorted(sidecar for _, sidecar, _ in proposals) == sorted(
        {f"{read.test}.gv-dependency.yaml" for read in UNDECLARED}
    )
    assert [verb for verb, sidecar, _ in proposals if sidecar == existing] == ["Append to"]
    for verb, sidecar, text in proposals:
        path = run.repo / sidecar
        assert path.exists() == (verb == "Append to")
        path.write_text((path.read_text(encoding="utf-8") if path.exists() else "") + text, encoding="utf-8")
        assert f"```yaml\n{text.rstrip()}\n```" in summary_path.read_text(encoding="utf-8")
    assert audit_cli(run, tmp_path, repo_config(), "--working-tree") == 0


def test_the_printed_commands_write_the_missing_declarations(
    audited_run: AuditedRun, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """INVARIANT: the record-and-write commands a failing audit prints leave no undeclared read when run."""
    run = copied_run(audited_run, tmp_path)
    config_path = tmp_path / "config.json"
    assert audit_cli(run, tmp_path, repo_config()) == EXIT_UNDECLARED
    printed = capsys.readouterr().out
    record = re.search(r"^  pytest -p (.+)$", printed, re.M)
    write_declarations = re.search(r"^  pytest-selective (audit .+)$", printed, re.M)
    assert record and write_declarations
    isolated = run.repo.parent / "isolated-pytest.ini"
    isolated.write_text("[pytest]\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(run.repo / "src"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    isolation = ["-c", str(isolated), "--basetemp", str(run.repo / ".audit-pytest-tmp"), "--rootdir", str(run.repo)]
    recorded = subprocess.run(
        [sys.executable, "-m", "pytest", *isolation, "-p", *record.group(1).split()],
        cwd=run.repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    monkeypatch.chdir(run.repo)
    arguments = write_declarations.group(1).split()
    assert arguments[arguments.index("--config") + 1] == str(config_path)
    cache = ["--repo", str(run.repo), "--cache", str(tmp_path / "cache.sqlite3")]
    assert main([*arguments, *cache]) == 0
    assert main(["audit", *cache, "--config", str(config_path), "--records", "impact-audit", "--working-tree"]) == 0


@pytest.mark.parametrize("github_actions", [True, False], ids=["github-actions", "elsewhere"])
def test_github_annotates_each_reading_test_file_once(
    audited_run: AuditedRun,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    github_actions: bool,
) -> None:
    """INVARIANT: on GitHub Actions each test file with undeclared reads gets one error annotation on that file."""
    if github_actions:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
    else:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert audit_cli(audited_run, tmp_path, repo_config()) == EXIT_UNDECLARED
    annotated = re.findall(r"^::error file=([^,]+),title=[^:]+::(.+)$", capsys.readouterr().out, re.M)
    expected = sorted({read.test for read in UNDECLARED}) if github_actions else []
    assert sorted(test for test, _ in annotated) == expected
    assert all(f"{test}.gv-dependency.yaml" in message for test, message in annotated)


def test_workflow_command_values_cannot_end_or_split_the_command() -> None:
    """INVARIANT: escaped text carries no newline, and a property carries no ``:`` or ``,`` separator."""
    assert _workflow_value("50% a\r\nb: c, d") == "50%25 a%0D%0Ab: c, d"
    assert _workflow_value("tests/a: b,c.py", property_value=True) == "tests/a%3A b%2Cc.py"


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
        ("os.posix_spawn", ("git", [b"git", b"--no-pager", b"-C", b"data", b"diff", b"--", b"value.txt"], {})),
        ("os.exec", ("/usr/bin/git", ["git", "--work-tree", "data", "diff", "--", "value.txt"], None)),
        ("os.spawn", (0, "git", ["git", "diff", "--", "value.txt"], {b"GIT_WORK_TREE": b"data"})),
        ("subprocess.Popen", ("git", ["git", "diff", "--", "value.txt"], None, {"GIT_WORK_TREE": "data"})),
    ],
)
def test_subprocess_arguments_naming_tracked_files_are_reads(
    recorder: ReadRecorder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str, args: tuple[object, ...]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert recorded(recorder, tmp_path, event, *args).inputs == {TEST: [DATA]}


def test_git_paths_follow_the_command_working_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init(repo)
    write(repo, "input.txt", "unrelated")
    write(repo, "nested tree/data/input.txt", "tracked input")
    write(
        repo,
        TEST,
        """
import subprocess

def test_git_diff(tmp_path):
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    subprocess.run(["git", "-C", tmp_path, "diff", "--", "input.txt"], check=True)
    subprocess.run(["git", "-C", "..", "-C", "nested tree/data", "diff", "--", "input.txt"],
                   cwd="tests", check=True)
""",
    )
    commit(repo)
    records = tmp_path / "records"
    result = run_audited_pytest(repo, records, TEST)
    assert result.returncode == 0, result.stdout + result.stderr
    reads = load_records(records)[0].inputs[TEST]
    assert "nested tree/data/input.txt" in reads
    assert "input.txt" not in reads


ROOT_INPUT = "input.txt"
NESTED_INPUT = "nested tree/data/input.txt"
GREP = '"grep", "-h", "-e", ".", "--"'
# Each case runs one real git command and states what git printed and which tracked file that was.
# `other` is a second repository outside the audited one whose input.txt holds "temporary".
GIT_COMMANDS = {
    "flag_before_chdir": (f'git("--no-pager", "-C", other, {GREP}, "input.txt")', "temporary", set()),
    "flag_after_chdir": (f'git("-C", other, "--no-pager", {GREP}, "input.txt")', "temporary", set()),
    "config_before_chdir": (
        f'git("-c", "core.quotePath=false", "-C", "nested tree/data", {GREP}, "input.txt")',
        "nested",
        {NESTED_INPUT},
    ),
    "empty_chdir": (f'git("-C", "nested tree", "-C", "", "-C", "data", {GREP}, "input.txt")', "nested", {NESTED_INPUT}),
    "work_tree": (
        f'git("--git-dir=" + other + "/.git", "--work-tree=" + other, {GREP}, "input.txt")',
        "temporary",
        set(),
    ),
    "work_tree_separate_value": (
        f'git("--git-dir", other + "/.git", "--work-tree", other, {GREP}, "input.txt")',
        "temporary",
        set(),
    ),
    "work_tree_after_chdir": (
        f'git("--git-dir", ".git", "--work-tree", ".", "-C", other, {GREP}, "input.txt")',
        "temporary",
        set(),
    ),
    "work_tree_environment": (
        f'git({GREP}, "input.txt", env=dict(os.environ, GIT_DIR=other + "/.git", GIT_WORK_TREE=other))',
        "temporary",
        set(),
    ),
    "work_tree_containing_the_directory": (
        f'git("--work-tree", "../..", {GREP}, "input.txt", cwd="nested tree/data")',
        "nested",
        {NESTED_INPUT},
    ),
    "top_magic": (f'git("-C", "nested tree/data", {GREP}, ":(top)input.txt")', "root", {ROOT_INPUT}),
    "top_short_magic": (f'git("-C", "nested tree/data", {GREP}, ":/input.txt")', "root", {ROOT_INPUT}),
    "top_magic_from_the_subprocess_directory": (
        f'git({GREP}, ":(top,literal)input.txt", cwd="nested tree/data")',
        "root",
        {ROOT_INPUT},
    ),
    "top_magic_in_a_work_tree": (
        f'git("--git-dir", other + "/.git", "--work-tree", other, {GREP}, ":(top)input.txt", cwd="nested tree")',
        "temporary",
        set(),
    ),
    "other_magic": (f'git("-C", "nested tree/data", {GREP}, ":(literal)input.txt")', "nested", {NESTED_INPUT}),
    "revision_path": ('git("-C", "nested tree/data", "show", "HEAD:input.txt")', "root", {ROOT_INPUT}),
    "revision_relative_path": ('git("-C", "nested tree/data", "show", "HEAD:./input.txt")', "nested", {NESTED_INPUT}),
    "revision_path_from_the_top": ('git("show", "HEAD:nested tree/data/input.txt")', "nested", {NESTED_INPUT}),
    "index_path": ('git("show", ":0:input.txt", cwd="nested tree/data")', "root", {ROOT_INPUT}),
    "index_path_elsewhere": ('git("-C", other, "show", ":input.txt")', "temporary", set()),
    "index_path_of_another_repository": ('git("--git-dir", other + "/.git", "show", ":input.txt")', "temporary", set()),
    # The file of a line range is relative to the directory git runs in, unlike the path after a revision.
    "line_range": (
        'git("log", "--format=", "-L1,1:input.txt", cwd="nested tree/data").splitlines()[-1]',
        "+nested",
        {NESTED_INPUT},
    ),
    "line_range_separate_value": (
        'git("-C", "nested tree/data", "log", "--format=", "-L", "1,1:input.txt").splitlines()[-1]',
        "+nested",
        {NESTED_INPUT},
    ),
    "line_range_of_a_function": (
        'git("-C", "nested tree/data", "log", "--format=", "-L", ":nested:input.txt").splitlines()[-1]',
        "+nested",
        {NESTED_INPUT},
    ),
    "option_value_with_a_colon": (
        'git("log", "-1", "--format=format:input.txt", cwd="nested tree/data")',
        "input.txt",
        set(),
    ),
    "revision_path_from_the_git_directory": ('git("show", "HEAD:input.txt", cwd=".git")', "root", {ROOT_INPUT}),
    # A repository without a work tree holds no file of the checkout around it.
    "bare_repository_inside_the_checkout": (
        '(git("-C", other, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",'
        ' "commit", "-qm", "fixture"), git("clone", "-q", "--bare", other, "build/remote.git"),'
        ' git("-C", "build/remote.git", "show", "HEAD:input.txt"))[-1]',
        "temporary",
        set(),
    ),
}
SHELL = "shell=True, check=True, capture_output=True, text=True"
if os.name == "posix":
    # The same commands as one POSIX shell command line.
    GIT_COMMANDS |= {
        "shell_command": (
            f'subprocess.run("git -C " + shlex.quote(other) + " grep -h -e . -- input.txt", {SHELL}).stdout',
            "temporary",
            set(),
        ),
        "shell_command_in_a_directory": (
            f"""subprocess.run("git -C 'nested tree/data' show HEAD:./input.txt", {SHELL}).stdout""",
            "nested",
            {NESTED_INPUT},
        ),
        "system": (
            """str(os.system("git -C 'nested tree/data' grep -q -e nested -- input.txt"))""",
            "0",
            {NESTED_INPUT},
        ),
        "shell_assignment": (
            f"""subprocess.run("GIT_PAGER=cat git -C 'nested tree/data' grep -h -e . -- input.txt", {SHELL}).stdout""",
            "nested",
            {NESTED_INPUT},
        ),
        "shell_assigned_work_tree": (
            'subprocess.run("GIT_DIR=" + shlex.quote(other + "/.git") + " GIT_WORK_TREE=" + shlex.quote(other)'
            f' + " git grep -h -e . -- input.txt", {SHELL}).stdout',
            "temporary",
            set(),
        ),
        "shell_reflog_revision": (
            f"""subprocess.run("git -C 'nested tree/data' show HEAD@{{0}}:input.txt", {SHELL}).stdout""",
            "root",
            {ROOT_INPUT},
        ),
        # Not one program with literal arguments: the recorder keeps reading every word where it is launched.
        "shell_pipeline": (
            f'subprocess.run("cd " + shlex.quote(other) + " && git grep -h -e . -- input.txt", {SHELL}).stdout',
            "temporary",
            {ROOT_INPUT},
        ),
        "shell_braces": (
            f"""subprocess.run("git -C 'nested tree/data' grep -h -e . -- input.txt {{a,b}}", {SHELL}).stdout""",
            "nested",
            {ROOT_INPUT},
        ),
    }


@pytest.fixture(scope="module")
def git_command_reads(tmp_path_factory: pytest.TempPathFactory) -> dict[str, set[str]]:
    """What the recorder attributes to each case's test file, of the two tracked input.txt files."""
    base = tmp_path_factory.mktemp("git-commands")
    repo = base / "repo"
    init(repo)
    write(repo, ROOT_INPUT, "root\n")
    write(repo, NESTED_INPUT, "nested\n")
    for name, (command, printed, _reads) in GIT_COMMANDS.items():
        write(
            repo,
            f"tests/test_{name}.py",
            f"""
import os
import shlex
import subprocess
from pathlib import Path

def git(*args, **options):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, **options).stdout

def test_git(tmp_path):
    other = str(tmp_path / "other")
    subprocess.run(["git", "init", "-q", other], check=True)
    Path(other, "input.txt").write_text("temporary\\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=other, check=True)
    assert {command}.strip() == {printed!r}
""",
        )
    commit(repo)
    result = run_audited_pytest(repo, base / "records", "tests")
    assert result.returncode == 0, result.stdout + result.stderr
    inputs = load_records(base / "records")[0].inputs
    return {name: {ROOT_INPUT, NESTED_INPUT} & set(inputs[f"tests/test_{name}.py"]) for name in GIT_COMMANDS}


@pytest.mark.parametrize("name", GIT_COMMANDS)
def test_git_operands_are_read_where_git_resolves_them(git_command_reads: dict[str, set[str]], name: str) -> None:
    assert git_command_reads[name] == GIT_COMMANDS[name][2]


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


def _reader_called_through(*modules: str) -> object:
    """A callable whose stack, innermost first, runs through functions of the named modules."""
    call = "recorder.audit('open', (path, 'r', 0))"
    reader: object = None
    for index, module in enumerate(modules):
        namespace: dict[str, object] = {"__name__": module, "inner": reader}
        body = call if index == 0 else "inner(recorder, path)"
        exec(f"def read(recorder, path):\n    {body}\n", namespace)
        reader = namespace["read"]
    return reader


@pytest.mark.parametrize(
    ("stack", "is_input"),
    [
        (("linecache", "traceback", "logging"), False),
        (("linecache", "warnings"), False),
        (("linecache", "inspect"), True),
        (("linecache",), True),
        (("traceback",), True),
    ],
    ids=["logged-traceback", "shown-warning", "inspect-getsource", "direct-linecache", "traceback-without-linecache"],
)
def test_only_source_shown_for_a_traceback_or_warning_is_not_a_test_input(
    recorder: ReadRecorder, tmp_path: Path, stack: tuple[str, ...], is_input: bool
) -> None:
    """
    INVARIANT: a source file opened to display one of its lines is not an input of the current test.

    A thread left running by an earlier test file logged an exception while a later file's test was
    current; rendering the traceback opened the earlier file, and the audit failed the later one.
    """
    read = _reader_called_through(*stack)
    assert callable(read)
    with recorder.attributed(tmp_path / TEST):
        read(recorder, str(tmp_path / DATA))
    assert recorder.record().inputs == ({TEST: [DATA]} if is_input else {})


def test_a_real_logged_traceback_through_another_tracked_file_records_no_read(tmp_path: Path) -> None:
    """Real pytest, real ``logging.exception``: the frame's file is opened only to render the traceback."""
    repo = tmp_path / "repo"
    repo.mkdir()
    init(repo)
    write(repo, "tests/test_earlier.py", "def test_earlier():\n    pass\n")
    write(
        repo,
        "tests/test_later.py",
        "import linecache\n"
        "import logging\n"
        "from pathlib import Path\n"
        "\n"
        "EARLIER = str(Path(__file__).with_name('test_earlier.py'))\n"
        "\n"
        "\n"
        "def test_logs_a_traceback_whose_frame_is_in_another_test_file():\n"
        "    # A frame that claims the other file, as a thread started there would have.\n"
        "    code = compile('\\n\\nraise RuntimeError(\"from a leftover thread\")', EARLIER, 'exec')\n"
        "    linecache.clearcache()\n"
        "    try:\n"
        "        exec(code, {})\n"
        "    except RuntimeError:\n"
        "        logging.getLogger('leftover').exception('background failure')\n",
    )
    commit(repo)
    result = run_audited_pytest(repo, Path("audit-records"), "tests/test_later.py")
    assert result.returncode == 0, result.stdout + result.stderr
    (record,) = load_records(repo / "audit-records")
    assert record.errors == []
    assert "tests/test_earlier.py" not in record.inputs.get("tests/test_later.py", [])


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
