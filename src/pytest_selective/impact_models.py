"""Validated contracts for cached, conservative test impact analysis."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pytest_selective.input_policy import DEFAULT_GLOBAL_INPUTS
from pytest_selective.test_inventory import TEST_FILE_PATTERNS

#: Marks a graph node that stands for a file's bytes: its readers inspect it without executing it.
CONTENTS_PREFIX = "@contents:"


def contents_node(path: str) -> str:
    """The node a content read of `path` depends on; it never follows `path`'s own imports."""
    return CONTENTS_PREFIX + path


def file_of(node: str) -> str:
    """The repository path a graph node stands for."""
    return node.removeprefix(CONTENTS_PREFIX)


class ImpactModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DependencyInputs(ImpactModel):
    """Canonical input semantics, shared by central and reader-owned rules."""

    inputs: list[str]
    reason: str = ""
    kind: Literal["content", "import"] = "import"


class DependencyRule(DependencyInputs):
    """Legacy central rule, retaining its content-only default."""

    readers: list[str]
    kind: Literal["content", "import"] = "content"
    reviewed_readers: dict[str, str] = Field(default_factory=dict)


class ManifestDependencyRule(DependencyInputs):
    inputs: list[str] = Field(min_length=1)
    readers: list[str] | None = Field(default=None, min_length=1)


class DependencyManifest(ImpactModel):
    dependencies: list[ManifestDependencyRule]


class DjangoURLConfPolicy(ImpactModel):
    """Opt-in consumers of a deferred Django ROOT_URLCONF registration."""

    settings_file: str
    http_tests: list[str] = Field(min_length=1)
    startup_tests: list[str] = Field(min_length=1)


class DeferredStringsRule(ImpactModel):
    """
    Module names one file only stores, and the files that actually load them.

    A module every test loads, such as Django settings, can name modules a framework imports only
    in some processes: Celery imports ``CELERY_IMPORTS`` only when a worker starts. Inside each of
    the ``assignments`` (each one top-level assignment in ``file``), those names stop being edges of
    ``file`` and become edges of every ``consumers`` file instead. Several settings the same
    processes load (Celery's imports, routes and Beat schedule) share one rule and one consumer
    list. The framework knowledge lives in the consumer's configuration; this rule only moves edges.
    """

    file: str
    #: Written ``"assignment": "X"`` for one, or ``"assignments": ["X", "Y"]`` for several.
    assignments: list[str] = Field(min_length=1)
    consumers: list[str] = Field(min_length=1)
    #: Text that marks a file as loading the deferred modules (e.g. ``start_worker(``). Planning
    #: fails when a file containing one is not a consumer, so a new loader can't silently lose them.
    consumer_markers: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _one_assignment_spelling(cls, data: object) -> object:
        if isinstance(data, dict) and "assignment" in data:
            if "assignments" in data:
                raise ValueError("give either assignment or assignments, not both")
            data = {**data, "assignments": [data["assignment"]]}
            del data["assignment"]
        return data

    @field_validator("assignments")
    @classmethod
    def _distinct_assignments(cls, assignments: list[str]) -> list[str]:
        if len(set(assignments)) != len(assignments):
            raise ValueError(f"assignments repeats a name: {assignments}")
        return assignments


class NameScopedModule(ImpactModel):
    """
    A module whose readers depend only on the top-level names they read, not on the whole file.

    A settings module, a constants module or a feature-flag table is read name by name, but every
    importer depends on the whole file, so changing one value selects every test that loads it: every
    test, when the module is global. Declared here, a change that only rebinds names selects the files
    that read those names. A changed import or other code, a call ``pure_calls`` does not name, a name
    code outside the repository reads, or an added or removed file keeps the module's ordinary edges.
    What the module's framework reads is the consumer's knowledge, so it lives here.
    """

    #: The module, repository-relative.
    file: str
    #: Tests that import the module. A narrowed change always runs them, so an edit that breaks
    #: loading the module fails even when no test reads what it changed.
    load_checks: list[str] = Field(min_length=1)
    #: Objects that expose the module's names as attributes, as dotted import paths
    #: (``django.conf.settings`` for Django settings). Reading one with a computed name
    #: (``getattr(settings, name)``) makes a file a reader of every name.
    accessors: list[str] = Field(default_factory=list)
    #: Names code outside the repository reads (a framework, an installed package). Changing one
    #: keeps the module's ordinary edges. `impact_name_scope.externally_read_names` computes them from
    #: an installed environment.
    external_names: list[str] = Field(default_factory=list)
    #: Prefixes of names read outside the repository under a namespace (Celery reads ``CELERY_*``).
    external_prefixes: list[str] = Field(default_factory=list)
    #: Callables computing a name may call without side effects, as written in the file, with ``*``
    #: for any run of characters (``config.*``, ``*.strip``). Any other call in a changed binding keeps
    #: the module's ordinary edges, because the call runs when the module loads.
    pure_calls: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class DeferredRoute(ImpactModel):
    """A `DeferredStringsRule` resolved against one tree."""

    file: str
    #: Module names found only inside the rule's assignment.
    strings: list[str]
    consumers: list[str]


class FirstPartyPackage(ImpactModel):
    """
    A locked dependency whose source repository this organization owns.

    A consumer's lock and manifest are global test inputs, so a pin move runs every test. For a
    package declared here the move is characterized instead: its old and new commits are fetched
    from ``repository`` and only consumer files reaching a changed module are selected. Fetching is
    only ever from ``repository``, never from a URL found in the lock under test.
    """

    #: Distribution name as it appears in the lock, e.g. ``gigaverse-backend-common``.
    name: str
    #: Clone URL, exactly as the lock and manifest spell it before any ``?rev=``.
    repository: str
    #: Top-level import package, e.g. ``backend_common``.
    import_prefix: str
    #: Directory holding the importable package inside ``repository``; only its files install.
    source_root: str = "src"
    lock: str = "uv.lock"
    manifest: str = "pyproject.toml"


class AuditExemption(ImpactModel):
    """
    Reads the read audit accepts without a graph edge, because another lane already covers them.

    Patterns use the declaration glob language, repository-root-relative, and each must match a
    tracked file: an exemption left behind by a rename is an error, not a silent hole.
    """

    readers: list[str] = Field(min_length=1)
    inputs: list[str] = Field(min_length=1)
    #: Names the lane that runs these readers when an input changes.
    reason: str = Field(min_length=1)


class ImpactConfig(ImpactModel):
    #: Environment changes can affect every test without any Python import edge.
    global_inputs: list[str] = Field(default_factory=lambda: list(DEFAULT_GLOBAL_INPUTS))
    #: Read by the audit only, so excluded from the graph's cache signature.
    audit_exemptions: list[AuditExemption] = Field(default_factory=list)
    #: The startup floor may not grow past this many files: `floor-budget` fails CI when a PR
    #: does. Unset, nothing is checked. Read by that check only, so excluded from the graph's
    #: cache signature like `audit_exemptions`.
    floor_budget: int | None = Field(default=None, ge=0)
    django_urlconf: DjangoURLConfPolicy | None = None
    deferred_strings: list[DeferredStringsRule] = Field(default_factory=list)
    #: Read at selection only, so excluded from the graph's cache signature.
    name_scoped_modules: list[NameScopedModule] = Field(default_factory=list)
    first_party_packages: list[FirstPartyPackage] = Field(default_factory=list)
    pytest_policy: dict[str, str] = Field(default_factory=dict)
    #: Repository-relative files passed through pytest -c; fingerprint their complete contents.
    pytest_config_files: list[str] = Field(default_factory=list)

    @field_validator("pytest_config_files")
    @classmethod
    def _pytest_config_paths(cls, paths: list[str]) -> list[str]:
        for path in paths:
            if (
                not path
                or path.startswith("/")
                or any(c in path for c in "\\:*?[]")
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise ValueError("pytest_config_files must contain literal repository-relative POSIX paths")
        return paths

    module_roots: list[str] = Field(default_factory=lambda: ["."])
    test_roots: list[str]
    test_patterns: list[str] = Field(default_factory=lambda: list(TEST_FILE_PATTERNS))
    scoped_hooks: dict[str, str] = Field(default_factory=dict)
    global_modules: list[str] = Field(default_factory=list)
    always_run: list[str] = Field(default_factory=list)
    ignored_changes: list[str] = Field(default_factory=list)
    dependencies: list[DependencyRule] = Field(default_factory=list)

    @field_validator("name_scoped_modules")
    @classmethod
    def one_declaration_per_module(cls, modules: list[NameScopedModule]) -> list[NameScopedModule]:
        files = [module.file for module in modules]
        if len(files) != len(set(files)):
            raise ValueError("name_scoped_modules declares a file more than once")
        return modules

    @field_validator("module_roots", "test_roots", "always_run", "ignored_changes", "global_inputs")
    @classmethod
    def relative_paths(cls, values: list[str]) -> list[str]:
        if any(
            value.startswith(("/", "\\")) or "\\" in value or ":" in value or ".." in value.split("/")
            for value in values
        ):
            raise ValueError("paths must be repository-relative POSIX paths")
        return values


class ImportSpec(ImpactModel):
    module: str
    names: list[str] = Field(default_factory=list)
    level: int = 0


class DependencyComment(ImpactModel):
    line: int
    text: str


class ParsedSource(ImpactModel):
    registered_plugins: list[str] | None = Field(default_factory=list)
    django_urlconf: str | None = None
    imports: list[ImportSpec]
    strings: list[str]
    opaque: list[str]
    pytest_plugin: bool
    dependencies: list[DependencyComment] = Field(default_factory=list)


class GitTree(ImpactModel):
    tree: str
    files: dict[str, str]
    links: list[str]


class Snapshot(ImpactModel):
    plugin_tests: list[str] = Field(default_factory=list)
    tree: str
    files: dict[str, str]
    edges: dict[str, list[str]]
    tests: list[str]
    opaque: dict[str, list[str]]
    unresolved: dict[str, list[str]]


class GraphAnalysisReport(ImpactModel):
    """Graph build statistics shared by cache warming and selection reports."""

    head: str
    total_files: int
    elapsed_seconds: float = 0
    parsed_blobs: int = 0
    snapshot_hits: int = 0


class AuditRecord(ImpactModel):
    """The tracked files each test file read or executed in one pytest process."""

    #: Test file to the repository files it opened or passed to a subprocess, both repository-relative.
    inputs: dict[str, list[str]] = Field(default_factory=dict)
    #: Audit hook failures; the hook swallows them so it can never change a test's outcome.
    errors: list[str] = Field(default_factory=list)


class UndeclaredRead(ImpactModel):
    test: str
    input: str


class AuditReport(ImpactModel):
    head: str
    records: int
    audited_tests: int
    recorded_reads: int
    #: Reads accepted without an edge: an `audit_exemptions` match, or a test in `always_run`.
    exempted_reads: int
    undeclared: list[UndeclaredRead]
    recorder_errors: list[str]


class ImpactReport(GraphAnalysisReport):
    mode: Literal["full", "scoped", "none"]
    #: True when every declared first-party lock and manifest is unchanged, or differs only by pins
    #: whose installed source is byte-identical. False whenever that is not proven, including when
    #: nothing is declared. Lanes that treat a lock change as "everything changed" may skip on it.
    dependencies_unchanged: bool = False
    base: str
    changed: list[str]
    #: The paths traversal started from: `changed`, with a narrowed first-party pin replaced by the
    #: files its moved modules reach. Explanations attribute selection to these, not to `changed`.
    seeds: list[str] = Field(default_factory=list)
    selected: list[str]
    reasons: list[str]


EdgeKind = Literal["import", "string", "package", "conftest", "startup", "declared"]


class PathStep(ImpactModel):
    """One file on an import path, and how it depends on the next step."""

    path: str
    #: How this file depends on the next step; None on the last step.
    kind: EdgeKind | None = None
    #: The line that creates the dependency, when one line does (an import, a dotted string).
    line: int | None = None


class SelectionRoute(ImpactModel):
    """A group of selected tests that reach the change the same way."""

    #: `floor`: through a changed startup-floor file. `changed`: test files the change edits.
    #: `funnel`: only through `via`. `other`: reached some other way. `unreached`: selected
    #: without reaching the change (always-run tests, an explicit full suite, fixed-shard padding).
    kind: Literal["floor", "changed", "funnel", "other", "unreached"]
    tests: int
    via: str | None = None
    #: The enclosing funnel, for a funnel nested inside another.
    parent: str | None = None


#: How most tests load a floor entry, which decides what shrinks what it pulls in.
#: `conftest`: an ancestor conftest. `hooks`: a conftest whose pytest hooks make it global.
#: `startup`: a configured startup module. `package`: a package initializer, run by every import
#: of the package's modules. `import`: a module most tests import. `declared`: a declared input.
FloorEntryKind = Literal["conftest", "hooks", "startup", "package", "import", "declared"]


class FloorEntry(ImpactModel):
    """A file most test files depend on directly: the floor is whatever the entries load."""

    path: str
    kind: FloorEntryKind
    #: Floor files this entry reaches, itself included.
    floor_files: int


class FloorCycle(ImpactModel):
    """
    The floor's largest import cycle: every member reaches every other.

    While the cycle holds, a startup file that loads one member loads all of them, so trimming
    what startup loads leaves the whole cycle in the floor as long as any route into it remains.
    """

    size: int
    #: The member the most other members depend on directly, where the cycle is easiest to see.
    hub: str
    hub_readers: int


class ChangedFileReach(ImpactModel):
    """
    One changed file's share of the selection: who loads it, and through what.

    `own` separates what the startup floor adds: the selected tests that would still load this
    file if the floor's entries (root conftest, startup modules, package initializers every test
    loads) imported nothing. Outside the floor, the hub is the file most of the remaining indirect
    loaders depend on directly on their way to the change, such as a directory conftest or a URL
    configuration a policy attaches to every HTTP test. Tests that import the change directly are
    its real users.
    """

    path: str
    #: Selected test files that depend on this file.
    tests: int
    #: Of those, test files that import it themselves.
    direct: int
    #: Of those, test files that still depend on it without the startup floor.
    own: int
    hub: str | None = None
    #: Selected test files that depend on `hub` directly and reach this file through it.
    hub_tests: int = 0
    hub_kind: FloorEntryKind | None = None


class FloorChange(ImpactModel):
    """The startup floor: non-test Python files that at least `share` of test files depend on."""

    share: float = Field(gt=0, le=1)
    before: int
    after: int
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    #: How the first added file enters the floor, from a file every test loads.
    path: list[PathStep] = Field(default_factory=list)
    #: The floor on this PR, sorted.
    files: list[str] = Field(default_factory=list)
    #: Files most tests depend on directly, largest share of the floor first: the floor is
    #: whatever these load, so they are where it shrinks.
    entries: list[FloorEntry] = Field(default_factory=list)
    cycle: FloorCycle | None = None


class BlastRadiusChange(ImpactModel):
    """A file whose change now selects many more test files than before this PR."""

    path: str
    before: int
    after: int
    #: A dependency this PR added that makes `path` reachable from more tests, then on to `path`.
    cause: list[PathStep] = Field(default_factory=list)


class ExplanationUnavailable(ImpactModel):
    """
    Written in place of an explanation when planning fell back to the complete suite.

    It replaces any explanation an earlier attempt of the same run uploaded, which would otherwise
    describe a plan this attempt did not run.
    """

    unavailable: str = Field(min_length=1)


class SelectionExplanation(ImpactModel):
    """Why a selection is as large as it is, and whether the change widened the graph."""

    base: str
    head: str
    selected: int
    total: int
    #: The complete suite ran because it was requested (a schedule, a dispatch, coverage, a label),
    #: not because the change reaches every test. Such a run times something other than a PR run.
    forced_full: bool = False
    #: The tree floor and widening deltas compare against: the PR's merge base, else `base`.
    graph_base: str
    #: Traversal seeds that are startup-floor files: each alone selects nearly every test.
    floor_seeds: list[str] = Field(default_factory=list)
    routes: list[SelectionRoute] = Field(default_factory=list)
    #: From the file the largest route passes through (or a startup root) to a changed file.
    path: list[PathStep] = Field(default_factory=list)
    floor: FloorChange
    #: The changed files carrying the most selected tests, largest first.
    changes: list[ChangedFileReach] = Field(default_factory=list)
    widened: list[BlastRadiusChange] = Field(default_factory=list)

    @property
    def natural_full_suite(self) -> bool:
        """The change itself reached every test: a run comparable with ordinary PR runs."""
        return self.full_suite and not self.forced_full

    @property
    def full_suite(self) -> bool:
        return self.total > 0 and self.selected == self.total

    @property
    def graph_widened(self) -> bool:
        """
        The floor grew, or a file now reaches many more tests.

        Net growth, not any added file: splitting a module swaps a small new file in for the
        larger ones that leave, which is what the floor advice asks for.
        """
        return self.floor.after > self.floor.before or bool(self.widened)

    @property
    def graph_narrowed(self) -> bool:
        return self.floor.after < self.floor.before and not self.widened

    @property
    def top_funnel(self) -> SelectionRoute | None:
        """The outermost funnel carrying the most selected tests; routes are ordered largest first."""
        return next((route for route in self.routes if route.kind == "funnel" and route.parent is None), None)
