"""A change to a name-scoped module selects the readers of the names it changes, or its ordinary dependents."""

from pathlib import Path

import pytest

from pytest_selective.impact_graph import GraphCache
from pytest_selective.impact_models import DeferredStringsRule, ImpactConfig, NameScopedModule
from pytest_selective.impact_name_scope import (
    NotNarrowed,
    changed_names,
    externally_read_names,
    named_readers,
    reads_unnamed,
)
from pytest_selective.impact_selection import affected
from tests.testing.git_repo import commit, init, write

SETTINGS = "src/proj/settings.py"
BASE_SETTINGS = """\
from proj.helpers import env

CACHE_TTL = 60
FEATURE_URL = env("FEATURE_URL", "https://feature.test")
FEATURE_ENDPOINT = FEATURE_URL + "/v1"
INSTALLED_APPS = ["proj"]
CELERY_IMPORTS = ("proj.tasks",)
SCHEDULE = {}
"""

POLICY = NameScopedModule(
    file=SETTINGS,
    load_checks=["tests/test_startup.py"],
    accessors=["framework.conf.settings"],
    external_names=["INSTALLED_APPS"],
    external_prefixes=["CELERY_"],
    pure_calls=["env"],
    reason="test settings are read by name",
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    init(root)
    write(root, "src/framework/__init__.py")
    write(root, "src/framework/conf.py", "settings = object()\n")
    write(root, "src/proj/__init__.py")
    write(root, "src/proj/helpers.py", "def env(name, default):\n    return default\n")
    write(root, SETTINGS, BASE_SETTINGS)
    write(root, "src/proj/tasks.py", "def work(): ...\n")
    write(
        root, "src/proj/cache.py", "from framework.conf import settings\n\ndef ttl():\n    return settings.CACHE_TTL\n"
    )
    write(
        root,
        "src/proj/feature.py",
        "from framework.conf import settings\n\ndef endpoint():\n    return settings.FEATURE_ENDPOINT\n",
    )
    write(root, "tests/test_cache.py", "from proj.cache import ttl\ndef test_ttl(): assert ttl()\n")
    write(root, "tests/test_feature.py", "from proj.feature import endpoint\ndef test_url(): assert endpoint()\n")
    write(root, "tests/test_other.py", "def test_other(): assert True\n")
    write(root, "tests/test_worker.py", "def test_worker(): assert True\n")
    write(root, "tests/test_startup.py", "def test_settings_load(): assert True\n")
    return root


@pytest.fixture
def config() -> ImpactConfig:
    return ImpactConfig(
        module_roots=["src", "."],
        test_roots=["tests"],
        global_modules=["proj.settings"],
        name_scoped_modules=[POLICY],
    )


@pytest.fixture
def cache(tmp_path: Path):
    cache = GraphCache(tmp_path / "cache.sqlite3")
    yield cache
    cache.close()


def edit_settings(repo: Path, old: str, new: str) -> tuple[str, str]:
    base = commit(repo)
    write(repo, SETTINGS, BASE_SETTINGS.replace(old, new))
    assert BASE_SETTINGS.replace(old, new) != BASE_SETTINGS
    return base, commit(repo)


def test_a_changed_name_selects_only_the_tests_that_read_it(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    report = affected(repo, base, head, config, cache)

    assert report.selected == ["tests/test_cache.py", "tests/test_startup.py"]
    assert any("CACHE_TTL" in reason for reason in report.reasons)


def test_a_name_computed_from_a_changed_one_changes_with_it(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base, head = edit_settings(repo, '"https://feature.test"', '"https://feature.example"')

    assert affected(repo, base, head, config, cache).selected == ["tests/test_feature.py", "tests/test_startup.py"]


def test_without_the_declaration_a_settings_change_still_selects_every_test(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert affected(repo, base, head, config.model_copy(update={"name_scoped_modules": []}), cache).mode == "full"


@pytest.mark.parametrize(
    ("old", "new", "why"),
    [
        (
            'INSTALLED_APPS = ["proj"]',
            'INSTALLED_APPS = ["proj", "extra"]',
            "code outside the repository reads INSTALLED_APPS",
        ),
        ('CELERY_IMPORTS = ("proj.tasks",)', 'CELERY_IMPORTS = ("proj.tasks", "proj.cache")', "CELERY_IMPORTS"),
        ("from proj.helpers import env\n", "from proj.helpers import env\nimport proj.cache\n", "runs code"),
        ("CACHE_TTL = 60", "CACHE_TTL = 60\nprint(CACHE_TTL)", "runs code"),
        ("CACHE_TTL = 60", "CACHE_TTL = compute()", "calls compute"),
    ],
    ids=["framework-setting", "framework-prefix", "changed-import", "code-reading-a-setting", "unknown-call"],
)
def test_a_change_it_cannot_prove_keeps_every_test(
    repo: Path, config: ImpactConfig, cache: GraphCache, old: str, new: str, why: str
) -> None:
    base, head = edit_settings(repo, old, new)

    report = affected(repo, base, head, config, cache)

    assert report.mode == "full"
    assert any(f"{SETTINGS} not narrowed" in reason and why in reason for reason in report.reasons), report.reasons


def test_a_deferred_name_reaches_its_declared_consumers(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    deferred = config.model_copy(
        update={
            "deferred_strings": [
                DeferredStringsRule(
                    file=SETTINGS,
                    assignments=["CELERY_IMPORTS"],
                    consumers=["tests/test_worker.py"],
                    reason="only the worker test starts a worker",
                )
            ]
        }
    )
    base, head = edit_settings(
        repo, 'CELERY_IMPORTS = ("proj.tasks",)', 'CELERY_IMPORTS = ("proj.tasks", "proj.cache")'
    )

    # The worker now loads proj.cache; the cache's own test is not affected by what the worker imports.
    assert affected(repo, base, head, deferred, cache).selected == ["tests/test_startup.py", "tests/test_worker.py"]


def test_each_assignment_of_a_deferred_rule_reaches_its_consumers(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    routes = 'CELERY_TASK_ROUTES = {"proj.tasks.work": "celery"}\n'
    write(repo, SETTINGS, BASE_SETTINGS + routes)
    deferred = config.model_copy(
        update={
            "deferred_strings": [
                DeferredStringsRule(
                    file=SETTINGS,
                    assignments=["CELERY_IMPORTS", "CELERY_TASK_ROUTES"],
                    consumers=["tests/test_worker.py"],
                    reason="only the worker test starts a worker",
                )
            ]
        }
    )
    base = commit(repo)
    write(repo, SETTINGS, BASE_SETTINGS + routes.replace('"celery"', '"billing"'))
    head = commit(repo)

    # The rule's second assignment changed: its consumer is selected, as for the first.
    assert affected(repo, base, head, deferred, cache).selected == ["tests/test_startup.py", "tests/test_worker.py"]


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (
            "tests/test_reload.py",
            "import importlib\nimport proj.settings as module\ndef test_reload(): importlib.reload(module)\n",
        ),
        ("tests/test_declared.py", f"# gv:test-dependency: {SETTINGS}\ndef test_declared(): assert True\n"),
        (
            "src/proj/dynamic.py",
            "from framework.conf import settings\n\ndef read(name):\n    return getattr(settings, name)\n",
        ),
    ],
    ids=["reloads-the-module", "declares-the-file", "computed-attribute-name"],
)
def test_a_file_that_reads_the_module_another_way_reads_every_name(
    repo: Path, config: ImpactConfig, cache: GraphCache, path: str, source: str
) -> None:
    write(repo, path, source)
    write(repo, "tests/test_dynamic.py", "from proj.dynamic import read\ndef test_read(): assert read\n")
    if path != "src/proj/dynamic.py":
        write(repo, "src/proj/dynamic.py", "def read(name):\n    return name\n")
    reader = "tests/test_dynamic.py" if path == "src/proj/dynamic.py" else path
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert affected(repo, base, head, config, cache).selected == sorted(
        {"tests/test_cache.py", "tests/test_startup.py", reader}
    )


def test_a_comment_only_change_runs_only_the_load_checks(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 60  # seconds")

    # No test reads a comment, but the module must still load.
    assert affected(repo, base, head, config, cache).selected == ["tests/test_startup.py"]


def test_a_mutating_call_rebinds_the_name_it_is_called_on() -> None:
    before = BASE_SETTINGS.encode()
    after = (BASE_SETTINGS + 'SCHEDULE.update({"tick": CACHE_TTL})\n').encode()

    assert changed_names(before, after, POLICY) == {"SCHEDULE"}


def test_an_unknown_call_inside_a_module_function_is_not_proven_pure() -> None:
    before = (BASE_SETTINGS + "def _ttl():\n    return 1\nLIMIT = _ttl()\n").encode()
    after = (BASE_SETTINGS + "def _ttl():\n    return compute()\nLIMIT = _ttl()\n").encode()

    with pytest.raises(NotNarrowed, match="calls _ttl"):
        changed_names(before, after, POLICY)


@pytest.mark.parametrize(
    ("source", "dynamic"),
    [
        ("from framework.conf import settings\nsettings.CACHE_TTL\n", False),
        ("from framework.conf import settings\ngetattr(settings, 'CACHE_TTL', 1)\n", False),
        ("from framework.conf import settings as s\ngetattr(s, name)\n", True),
        ("from framework.conf import settings\nvars(settings)\n", True),
        ("from framework.conf import settings\nsettings.__dict__\n", True),
        ("settings = load()\ngetattr(settings, name)\n", False),
        ("from framework.conf import settings\nconfigure(settings)\n", True),
        ("import proj.settings as module\nmodule.CACHE_TTL\n", False),
        ("import importlib\nimport proj.settings as module\nimportlib.reload(module)\n", True),
        ("import proj.settings\n", True),
        ("from . import settings\nsettings.CACHE_TTL\n", False),
        ("from . import settings as s\nconfigure(s)\n", True),
        ("from .settings import *\n", True),
        ("from proj.settings import *\n", True),
        ("from proj.settings import CACHE_TTL\nconfigure(CACHE_TTL)\n", False),
    ],
)
def test_dynamic_reads_are_only_those_through_an_accessor_or_the_module(source: str, dynamic: bool) -> None:
    assert reads_unnamed(source.encode(), ["framework.conf.settings"], ["proj.settings"], ["proj"]) is dynamic


def test_externally_read_names_are_the_names_installed_code_mentions(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    write(site, "framework/core.py", "def setup(conf):\n    return conf.INSTALLED_APPS\n")
    write(site, "other/README.py", "# CACHE_TTLS is a different name\n")

    assert externally_read_names(BASE_SETTINGS.encode(), [site], r"[A-Z][A-Z0-9_]*") == {"INSTALLED_APPS"}


@pytest.mark.parametrize(
    ("text", "mentioned"),
    [
        pytest.param("conf.CACHE_TTL", True, id="attribute"),
        pytest.param("x=CACHE_TTL;", True, id="between-punctuation"),
        pytest.param("CACHE_TTL", True, id="whole-file"),
        pytest.param("CACHE_TTLS", False, id="longer-name"),
        pytest.param("MY_CACHE_TTL", False, id="prefixed-name"),
        pytest.param("1CACHE_TTL", False, id="after-digit"),
        pytest.param("éCACHE_TTL", True, id="after-non-ascii-byte"),
    ],
)
def test_a_name_counts_only_as_a_whole_word(tmp_path: Path, text: str, mentioned: bool) -> None:
    write(tmp_path, "pkg/mod.py", text + "\n")

    assert externally_read_names(b"CACHE_TTL = 1\n", [tmp_path]) == ({"CACHE_TTL"} if mentioned else set())


def test_importing_one_name_from_the_module_reads_only_that_name(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo, "tests/test_direct.py", "from proj.settings import FEATURE_URL\ndef test_direct(): assert FEATURE_URL\n"
    )
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert affected(repo, base, head, config, cache).selected == ["tests/test_cache.py", "tests/test_startup.py"]


def test_naming_the_module_for_a_framework_to_load_reads_no_name(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    # Like DJANGO_SETTINGS_MODULE: the framework loads the module, and what it reads is framework_settings.
    write(
        repo, "tests/test_boot.py", 'import os\nos.environ["SETTINGS_MODULE"] = "proj.settings"\ndef test_boot(): ...\n'
    )
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert "tests/test_boot.py" not in affected(repo, base, head, config, cache).selected


def test_a_non_global_constants_module_narrows_to_the_importers_that_read_the_changed_name(
    repo: Path, cache: GraphCache
) -> None:
    # Nothing about settings or startup: an ordinary module two tests import, each reading one name.
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 20\nTIMEOUT = 5\n")
    write(repo, "tests/test_pages.py", "from proj import limits\ndef test_pages(): assert limits.PAGE_SIZE\n")
    write(repo, "tests/test_timeout.py", "from proj.limits import TIMEOUT\ndef test_timeout(): assert TIMEOUT\n")
    write(repo, "tests/test_limits_load.py", "import proj.limits as limits\ndef test_load(): assert limits.TIMEOUT\n")
    constants = NameScopedModule(
        file="src/proj/limits.py", load_checks=["tests/test_limits_load.py"], reason="read name by name"
    )
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], name_scoped_modules=[constants])
    base = commit(repo)
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 50\nTIMEOUT = 5\n")
    head = commit(repo)

    assert affected(repo, base, head, config, cache).selected == ["tests/test_limits_load.py", "tests/test_pages.py"]
    # Without the declaration every importer is selected.
    plain = config.model_copy(update={"name_scoped_modules": []})
    assert "tests/test_timeout.py" in affected(repo, base, head, plain, cache).selected


def test_each_declared_module_narrows_independently(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 20\n")
    write(repo, "tests/test_pages.py", "from proj.limits import PAGE_SIZE\ndef test_pages(): assert PAGE_SIZE\n")
    limits = NameScopedModule(file="src/proj/limits.py", load_checks=["tests/test_pages.py"], reason="constants")
    both = config.model_copy(update={"name_scoped_modules": [POLICY, limits]})
    base = commit(repo)
    write(repo, SETTINGS, BASE_SETTINGS.replace("CACHE_TTL = 60", "CACHE_TTL = 90"))
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 50\n")
    head = commit(repo)

    report = affected(repo, base, head, both, cache)

    assert report.selected == ["tests/test_cache.py", "tests/test_pages.py", "tests/test_startup.py"]
    assert sum("narrowed" in reason for reason in report.reasons) == 2


def test_a_sidecar_that_declares_the_module_reads_every_name(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "tests/test_text.py", "def test_text(): assert True\n")
    write(
        repo,
        "tests/test_text.py.gv-dependency.yaml",
        f"dependencies:\n  - kind: content\n    inputs:\n      - '//{SETTINGS}'\n",
    )
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert "tests/test_text.py" in affected(repo, base, head, config, cache).selected


def test_a_module_may_be_declared_only_once() -> None:
    with pytest.raises(ValueError, match="more than once"):
        ImpactConfig(test_roots=["tests"], name_scoped_modules=[POLICY, POLICY])


def test_a_removed_name_selects_the_files_that_read_it(repo: Path, config: ImpactConfig, cache: GraphCache) -> None:
    base, head = edit_settings(repo, "CACHE_TTL = 60\n", "")

    assert affected(repo, base, head, config, cache).selected == ["tests/test_cache.py", "tests/test_startup.py"]


def test_a_call_to_a_module_function_is_pure_when_its_own_calls_are() -> None:
    helper = "def _ttl(seconds):\n    return env('TTL', seconds)\n"
    before = (BASE_SETTINGS + helper + "LIMIT = _ttl(1)\n").encode()
    after = (BASE_SETTINGS + helper + "LIMIT = _ttl(2)\n").encode()

    assert changed_names(before, after, POLICY) == {"LIMIT"}


def test_a_relative_import_that_reads_names_dynamically_reads_every_name(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(repo, "src/proj/lookup.py", "from . import settings\n\ndef read(name):\n    return getattr(settings, name)\n")
    write(repo, "tests/test_lookup.py", "from proj.lookup import read\ndef test_read(): assert read\n")
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert "tests/test_lookup.py" in affected(repo, base, head, config, cache).selected


def test_a_changed_decorated_function_is_code_because_its_decorator_may_register_it() -> None:
    before = (BASE_SETTINGS + "@receiver(saved)\ndef on_save(sender):\n    return 1\n").encode()
    after = (BASE_SETTINGS + "@receiver(saved)\ndef on_save(sender):\n    return 2\n").encode()

    with pytest.raises(NotNarrowed, match="runs code"):
        changed_names(before, after, POLICY)


def test_a_file_that_mentions_a_changed_name_without_loading_the_module_is_not_a_reader(
    repo: Path, cache: GraphCache
) -> None:
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 20\n")
    write(repo, "tests/test_pages.py", "from proj.limits import PAGE_SIZE\ndef test_pages(): assert PAGE_SIZE\n")
    # Its own PAGE_SIZE, unrelated to the module's.
    write(repo, "src/proj/paging.py", "PAGE_SIZE = 10\n")
    write(repo, "tests/test_paging.py", "from proj.paging import PAGE_SIZE\ndef test_paging(): assert PAGE_SIZE\n")
    constants = NameScopedModule(file="src/proj/limits.py", load_checks=["tests/test_pages.py"], reason="constants")
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], name_scoped_modules=[constants])
    base = commit(repo)
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 50\n")
    head = commit(repo)

    assert affected(repo, base, head, config, cache).selected == ["tests/test_pages.py"]


def test_moving_a_binding_changes_the_names_it_binds() -> None:
    before = (BASE_SETTINGS + "LIMIT = 1\nLIMIT = 2\n").encode()
    after = (BASE_SETTINGS + "LIMIT = 2\nLIMIT = 1\n").encode()

    assert changed_names(before, after, POLICY) == {"LIMIT"}


def test_a_changed_module_docstring_changes_the_module_doc() -> None:
    before = ('"""Old help."""\n' + BASE_SETTINGS).encode()
    after = ('"""New help."""\n' + BASE_SETTINGS).encode()

    assert changed_names(before, after, POLICY) == {"__doc__"}


def test_a_reader_whose_own_source_is_read_does_not_select_that_source_reader(repo: Path, cache: GraphCache) -> None:
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 20\n")
    write(repo, "tests/test_pages.py", "from proj.limits import PAGE_SIZE\ndef test_pages(): assert PAGE_SIZE\n")
    # Reads test_pages.py's text, which a change to PAGE_SIZE's value leaves unchanged.
    write(repo, "tests/test_source_lint.py", "def test_lint(): assert True\n")
    write(
        repo,
        "tests/test_source_lint.py.gv-dependency.yaml",
        "dependencies:\n  - kind: content\n    inputs:\n      - '//tests/test_pages.py'\n",
    )
    constants = NameScopedModule(file="src/proj/limits.py", load_checks=["tests/test_pages.py"], reason="constants")
    config = ImpactConfig(module_roots=["src", "."], test_roots=["tests"], name_scoped_modules=[constants])
    base = commit(repo)
    write(repo, "src/proj/limits.py", "PAGE_SIZE = 50\n")
    head = commit(repo)

    narrowed = affected(repo, base, head, config, cache).selected
    ordinary = affected(repo, base, head, config.model_copy(update={"name_scoped_modules": []}), cache).selected

    assert narrowed == ["tests/test_pages.py"]
    assert set(narrowed) <= set(ordinary)


@pytest.mark.parametrize(
    ("source", "reads"),
    [
        ("from framework.conf import settings\nsettings.CACHE_TTL\n", True),
        ("from framework.conf import settings\ngetattr(settings, 'CACHE_TTL', 1)\n", True),
        ("@override_settings(CACHE_TTL=1)\ndef test_ttl(): ...\n", True),
        ("from proj.settings import CACHE_TTL\n", True),
        ("ROUTES = {'CACHE_TTL': 'cache'}\n", True),
        ("from framework.conf import settings\n# Callers tune CACHE_TTL in settings.\nsettings.OTHER\n", False),
        ('"""Reads CACHE_TTL through the cache."""\nfrom proj.cache import ttl\n', False),
        ('def ttl():\n    """CACHE_TTL, in seconds."""\n    return 1\n', False),
        ('class Cache:\n    """Expires after CACHE_TTL."""\n', False),
        ('async def ttl():\n    """CACHE_TTL, in seconds."""\n', False),
        # A string that is not the first statement of a body is data, not a docstring.
        ('def ttl():\n    x = 1\n    "CACHE_TTL"\n', True),
        # A file that does not parse keeps the textual match.
        ("settings.CACHE_TTL(\n", True),
    ],
)
def test_only_code_that_mentions_a_name_reads_it(source: str, reads: bool) -> None:
    """Comments and docstrings never run, so a name mentioned only there is not read."""
    assert bool(named_readers({"src/proj/x.py": source.encode()}, {"CACHE_TTL"}, exclude=SETTINGS)) is reads


def test_a_loader_that_mentions_a_changed_name_only_in_prose_is_not_selected(
    repo: Path, config: ImpactConfig, cache: GraphCache
) -> None:
    write(
        repo,
        "src/proj/notes.py",
        '"""Callers tune CACHE_TTL."""\nfrom framework.conf import settings\n\n\n'
        "def other():\n    # Not CACHE_TTL: this reads FEATURE_URL.\n    return settings.FEATURE_URL\n",
    )
    write(repo, "tests/test_notes.py", "from proj.notes import other\ndef test_other(): assert other()\n")
    base, head = edit_settings(repo, "CACHE_TTL = 60", "CACHE_TTL = 90")

    assert affected(repo, base, head, config, cache).selected == ["tests/test_cache.py", "tests/test_startup.py"]
