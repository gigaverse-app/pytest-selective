// What pytest-selective promises about one small repository, commit after commit.
//
// The selected tests are exactly the tests that reach a changed file, in the base or the head
// tree, through imports, ancestor conftests or import-kind declarations, or that reach a reader
// of a changed file's contents. A content read does not follow the read file's imports. A change to a
// global input selects every test. Unparseable Python in either tree is an error, never a
// narrower or a full selection. `observed` holds the selection between the last two commits and
// between the history's first commit and the last one, as a pull request's base and head.
//
// `missed` is the independent check: the driver runs pytest's collection on both trees, records
// which repository files each test really imports or opens, and lists the tests that loaded a
// changed file but were not selected. It must always be empty.
//
// The planner keeps a graph cache across plans. It is never part of the specification: every
// answer below depends only on the trees and the configuration, so a configuration change, a
// restarted cache or a damaged cache entry must leave each answer exactly what a cold plan gives.
module selection {
  type Event = { op: str, file: str, target: str }
  type Selection = { mode: str, selected: Set[str] }
  type View = { mode: str, selected: Set[str], sinceStart: Selection, missed: Set[str] }
  type Tree = {
    imports: Set[(str, str)],
    present: Set[str],
    declared: Set[(str, str)],
    versions: str -> int,
    broken: Set[str],
    requirements: int,
    // Tests that read data/table.json with open() and a literal path, at import time.
    reads: Set[str],
  }
  type Content = {
    present: bool,
    imports: Set[(str, str)],
    declared: Set[(str, str)],
    version: int,
    broken: bool,
    reads: bool,
  }
  // narrow: test_roots is tests/sub instead of tests. tableGlobal: data/table.json is a global input.
  type Config = { narrow: bool, tableGlobal: bool }

  pure val MODULES = Set("alpha", "beta", "gamma")
  // src/pkg/__init__.py, with `__all__ = ["alpha"]`. Importing any pkg module executes it.
  pure val INIT = "init"
  // plug.py, loaded into every pytest session by `addopts = -p plug` in pytest.ini.
  pure val PLUGIN = "plugin"
  // tests/helpers.py: a module inside the test root that is not a test.
  pure val HELPER = "helper"
  // tests/conftest.py and tests/sub/conftest.py.
  pure val CONFTESTS = Set("conftest", "subconftest")
  // tests/test_one.py, tests/test_two.py and tests/sub/test_sub.py.
  pure val TESTS = Set("test_one", "test_two", "test_sub")
  pure val PYTHON = MODULES.union(Set(HELPER, INIT, PLUGIN)).union(CONFTESTS).union(TESTS)
  // Every file in the graph: the Python files and a data table.
  pure val FILES = PYTHON.union(Set("table"))
  // What an import names. "star" is `from pkg import *`, which imports pkg.alpha through
  // `__all__`. "helperBare" is `import helpers`, which pytest's default prepend import mode
  // resolves to tests/helpers.py for files directly in tests/.
  pure val TARGETS = MODULES.union(Set(HELPER, "star", "helperBare"))
  // Files allowed to spell each kind of import.
  pure val MODULE_IMPORTERS = PYTHON.exclude(Set(PLUGIN))
  pure val STAR_IMPORTERS = TESTS.union(CONFTESTS).union(Set(HELPER))
  pure val BARE_IMPORTERS = Set("test_one", "test_two", "conftest")

  // The file an import resolves to.
  pure def resolved(target: str): str =
    if (target == "star") "alpha" else if (target == "helperBare") HELPER else target
  // Files a test can declare it reads with a `# gv:test-dependency:` comment (import kind).
  pure val DECLARABLE = Set("table", "gamma")
  // Sidecars declare that test_sub reads gamma's contents and that tests/helpers.py reads the
  // table's (content kind). They never change, and exist while their reader does.
  pure val CONTENT_READS = Set(("test_sub", "gamma"), (HELPER, "table"))
  // Files a commit may delete and add back.
  pure val REMOVABLE = Set("alpha", "beta", HELPER, "test_one", "test_two")
  pure val OPTIONS = Set("narrow", "tableGlobal")

  var tree: Tree
  // The tree before the last commit, the base a rerun of the last plan compares against.
  var previous: Tree
  // The history's first tree, compared with every later one as a pull request's base.
  var start: Tree
  var config: Config
  var event: Event
  var observed: View

  // What one file's bytes are made of, so that equal contents compare equal.
  pure def content(t: Tree, f: str): Content =
    if (t.present.contains(f))
      {
        present: true,
        imports: t.imports.filter(e => e._1 == f),
        declared: t.declared.filter(d => d._1 == f),
        version: t.versions.get(f),
        broken: t.broken.contains(f),
        reads: t.reads.contains(f),
      }
    else { present: false, imports: Set(), declared: Set(), version: 0, broken: false, reads: false }

  // The files collected as tests under a configuration.
  pure def testsOf(c: Config): Set[str] = if (c.narrow) Set("test_sub") else TESTS

  // The dependency edges of one tree: imports and import-kind declarations between files that
  // exist, and each test's ancestor conftests.
  pure def edges(t: Tree, c: Config): Set[(str, str)] = {
    val spelled = t.imports.map(e => (e._1, resolved(e._2))).union(t.declared)
    val linked = spelled.filter(e => t.present.contains(e._1) and t.present.contains(e._2))
    val packaged = t.imports.filter(e => MODULES.union(Set("star")).contains(e._2) and t.present.contains(e._1))
      .map(e => (e._1, INIT))
    val tests = testsOf(c).intersect(t.present)
    val root = tests.map(test => (test, "conftest"))
    val plugin = tests.map(test => (test, PLUGIN))
    linked.union(packaged).union(root).union(plugin).union(Set(("test_sub", "subconftest")))
  }

  // The files that reach `changed` along `e`, the changed files included. Folding once per file
  // is enough steps to follow any path between them.
  pure def reaching(e: Set[(str, str)], changed: Set[str]): Set[str] =
    FILES.fold(changed, (found, _) => found.union(e.filter(x => found.contains(x._2)).map(x => x._1)))

  pure def selection(before: Tree, after: Tree, c: Config): Selection =
    if (before.broken.size() > 0 or after.broken.size() > 0) { mode: "error", selected: Set() }
    else {
      val changed = FILES.filter(f => content(before, f) != content(after, f))
      val global = before.requirements != after.requirements or (c.tableGlobal and changed.contains("table"))
      val tests = testsOf(c).intersect(after.present)
      // A literal path read is a content read, like a kind: content sidecar.
      val literal = before.reads.union(after.reads).map(f => (f, "table"))
      val readers = CONTENT_READS.union(literal)
        .filter(r => changed.contains(r._2) and (before.present.contains(r._1) or after.present.contains(r._1)))
        .map(r => r._1)
      val chosen = if (global) tests
        else reaching(edges(before, c).union(edges(after, c)), changed.union(readers)).intersect(tests)
      {
        mode: if (global or (chosen.size() > 0 and chosen == tests)) "full" else if (chosen.size() > 0) "scoped" else "none",
        selected: chosen,
      }
    }

  // One commit from the current tree to `following`, and the selections it produces.
  action commit(op: str, file: str, target: str, following: Tree): bool = {
    val latest = selection(tree, following, config)
    all {
      tree' = following,
      previous' = tree,
      start' = start,
      config' = config,
      event' = { op: op, file: file, target: target },
      observed' = {
        mode: latest.mode,
        selected: latest.selected,
        sinceStart: selection(start, following, config),
        missed: Set(),
      },
    }
  }

  // Plan the last commit again, against the previous and the first commit, with `nextConfig` as the
  // configuration and the cache as the preceding operation left it. Each caller assigns `event`.
  action replan(nextConfig: Config): bool = {
    val latest = selection(previous, tree, nextConfig)
    all {
      tree' = tree,
      previous' = previous,
      start' = start,
      config' = nextConfig,
      observed' = {
        mode: latest.mode,
        selected: latest.selected,
        sinceStart: selection(start, tree, nextConfig),
        missed: Set(),
      },
    }
  }

  pure val INITIAL: Tree = {
    imports: Set(("test_one", "alpha"), ("alpha", "beta"), ("test_two", "gamma"), ("test_sub", HELPER)),
    present: FILES,
    declared: Set(("test_two", "table")),
    versions: FILES.mapBy(_ => 0),
    broken: Set(),
    requirements: 0,
    reads: Set(),
  }

  action init = all {
    tree' = INITIAL,
    previous' = INITIAL,
    start' = INITIAL,
    config' = { narrow: false, tableGlobal: false },
    event' = { op: "init", file: "", target: "" },
    observed' = { mode: "none", selected: Set(), sinceStart: { mode: "none", selected: Set() }, missed: Set() },
  }

  // Change a file's body without changing what it imports or declares.
  action edit(file: str): bool = all {
    tree.present.contains(file),
    commit("edit", file, "", { ...tree, versions: tree.versions.set(file, tree.versions.get(file) + 1) }),
  }

  action link(file: str, target: str): bool = all {
    if (target == "star") STAR_IMPORTERS.contains(file)
      else if (target == "helperBare") BARE_IMPORTERS.contains(file)
      else MODULE_IMPORTERS.contains(file),
    TARGETS.contains(target),
    file != resolved(target),
    tree.present.contains(file),
    tree.present.contains(resolved(target)),
    not(tree.imports.contains((file, target))),
    commit("link", file, target, { ...tree, imports: tree.imports.union(Set((file, target))) }),
  }

  action unlink(file: str, target: str): bool = all {
    tree.present.contains(file),
    tree.imports.contains((file, target)),
    commit("unlink", file, target, { ...tree, imports: tree.imports.exclude(Set((file, target))) }),
  }

  // Delete a file. Its importers keep spelling the import, which no longer resolves.
  action remove(file: str): bool = all {
    REMOVABLE.contains(file),
    tree.present.contains(file),
    commit("remove", file, "", {
      ...tree,
      imports: tree.imports.filter(e => e._1 != file),
      present: tree.present.exclude(Set(file)),
      declared: tree.declared.filter(d => d._1 != file),
      broken: tree.broken.exclude(Set(file)),
      reads: tree.reads.exclude(Set(file)),
    }),
  }

  // Add a deleted file back, importing and declaring nothing.
  action restore(file: str): bool = all {
    REMOVABLE.contains(file),
    not(tree.present.contains(file)),
    commit("restore", file, "", { ...tree, present: tree.present.union(Set(file)) }),
  }

  action declare(file: str, target: str): bool = all {
    TESTS.contains(file),
    tree.present.contains(file),
    DECLARABLE.contains(target),
    not(tree.declared.contains((file, target))),
    commit("declare", file, target, { ...tree, declared: tree.declared.union(Set((file, target))) }),
  }

  action undeclare(file: str, target: str): bool = all {
    tree.declared.contains((file, target)),
    commit("undeclare", file, target, { ...tree, declared: tree.declared.exclude(Set((file, target))) }),
  }

  // Make a Python file unparseable, keeping everything else it spells.
  action breakSyntax(file: str): bool = all {
    PYTHON.contains(file),
    tree.present.contains(file),
    not(tree.broken.contains(file)),
    commit("breakSyntax", file, "", { ...tree, broken: tree.broken.union(Set(file)) }),
  }

  action repair(file: str): bool = all {
    tree.broken.contains(file),
    commit("repair", file, "", { ...tree, broken: tree.broken.exclude(Set(file)) }),
  }

  // Make a test read data/table.json with open() and a literal path, without declaring it.
  action readTable(file: str): bool = all {
    TESTS.contains(file),
    tree.present.contains(file),
    not(tree.reads.contains(file)),
    commit("readTable", file, "", { ...tree, reads: tree.reads.union(Set(file)) }),
  }

  action touchGlobal = commit("touchGlobal", "", "", { ...tree, requirements: tree.requirements + 1 })

  // Flip one configuration option, then plan the last commit again.
  action toggleConfig(option: str): bool = all {
    OPTIONS.contains(option),
    replan(if (option == "narrow") { ...config, narrow: not(config.narrow) }
      else { ...config, tableGlobal: not(config.tableGlobal) }),
    event' = { op: "toggleConfig", file: option, target: "" },
  }

  // Close the cache (which prunes it) and open it again, then plan the last commit again.
  action restart = all { replan(config), event' = { op: "restart", file: "", target: "" } }

  // Damage every stored graph without updating its checksum, then plan the last commit again.
  action corrupt = all { replan(config), event' = { op: "corrupt", file: "", target: "" } }

  // A step that commits nothing, so that a witness can end in an assertion.
  action inspect = all {
    tree' = tree,
    previous' = previous,
    start' = start,
    config' = config,
    event' = { op: "inspect", file: "", target: "" },
    observed' = observed,
  }

  action step = {
    nondet file = FILES.oneOf()
    nondet target = TARGETS.union(DECLARABLE).oneOf()
    nondet option = OPTIONS.oneOf()
    any {
      edit(file),
      link(file, target),
      unlink(file, target),
      remove(file),
      restore(file),
      declare(file, target),
      undeclare(file, target),
      breakSyntax(file),
      repair(file),
      readTable(file),
      touchGlobal,
      toggleConfig(option),
      restart,
      corrupt,
    }
  }

  val selectsOnlyExistingTests = observed.missed.size() == 0 and observed.selected.subseteq(testsOf(config).intersect(tree.present))
    and observed.sinceStart.selected.subseteq(testsOf(config).intersect(tree.present))

  pure def view(mode: str, selected: Set[str]): View =
    { mode: mode, selected: selected, sinceStart: { mode: mode, selected: selected }, missed: Set() }

  run transitiveEditTest = init.then(edit("beta"))
    .then(all { assert(observed == view("scoped", Set("test_one"))), inspect })

  run deletedModuleSelectsFormerImportersTest = init.then(remove("beta"))
    .then(all { assert(observed == view("scoped", Set("test_one"))), inspect })

  // test_two declares the table; tests/helpers.py reads it as content, and test_sub imports the helper.
  run declaredReadTest = init.then(edit("table"))
    .then(all { assert(observed == view("scoped", Set("test_two", "test_sub"))), inspect })

  run conftestSelectsEveryTestTest = init.then(edit("conftest"))
    .then(all { assert(observed == view("full", TESTS)), inspect })

  run nestedConftestSelectsItsSubtreeTest = init.then(edit("subconftest"))
    .then(all { assert(observed == view("scoped", Set("test_sub"))), inspect })

  run globalInputSelectsEveryTestTest = init.then(touchGlobal)
    .then(all { assert(observed == view("full", TESTS)), inspect })

  run newImportWidensSelectionTest = init.then(link("test_two", "alpha")).then(edit("beta"))
    .then(all { assert(observed.selected == Set("test_one", "test_two")), inspect })

  run deletedTestIsNotSelectedTest = init.then(remove("test_one")).then(edit("beta"))
    .then(all { assert(observed.mode == "none" and observed.sinceStart.selected == Set()), inspect })

  run removedDeclarationStopsSelectingTest = init.then(undeclare("test_two", "table")).then(edit("table"))
    // test_sub still follows the table through the helper's content read.
    .then(all { assert(observed.selected == Set("test_sub") and observed.sinceStart.selected == Set("test_two", "test_sub")), inspect })

  run helperModuleSelectsItsImportersTest = init.then(link(HELPER, "beta")).then(edit("beta"))
    .then(all { assert(observed == view("scoped", Set("test_one", "test_sub"))), inspect })

  run contentReadIsNotTransitiveTest = init.then(link("gamma", "beta")).then(edit("beta"))
    .then(all { assert(observed.selected == Set("test_one", "test_two")), inspect })

  run contentReadSelectsOnItsFileTest = init.then(edit("gamma"))
    .then(all { assert(observed == view("scoped", Set("test_two", "test_sub"))), inspect })

  run importDeclarationFollowsImportsTest = init.then(link("gamma", "beta")).then(declare("test_sub", "gamma"))
    .then(edit("beta"))
    .then(all { assert(observed.selected == TESTS), inspect })

  run unparseableSourceIsAnErrorTest = init.then(breakSyntax("beta")).then(repair("beta"))
    .then(all {
      // The base is still unparseable; against the first commit nothing changed.
      assert(observed == { mode: "error", selected: Set(), sinceStart: { mode: "none", selected: Set() }, missed: Set() }),
      inspect,
    })

  run revertedImportIsNoChangeSinceStartTest = init.then(link("gamma", "alpha")).then(unlink("gamma", "alpha"))
    .then(all {
      assert(observed == { mode: "scoped", selected: Set("test_two", "test_sub"), sinceStart: { mode: "none", selected: Set() }, missed: Set() }),
      inspect,
    })

  run narrowedTestRootsReplanFromScratchTest = init.then(edit("beta")).then(toggleConfig("narrow"))
    .then(all { assert(observed == view("none", Set())), inspect })

  run tableAsGlobalInputSelectsEveryTestTest = init.then(toggleConfig("tableGlobal")).then(edit("table"))
    .then(all { assert(observed == view("full", TESTS)), inspect })

  run damagedCacheIsRebuiltTest = init.then(edit("beta")).then(corrupt)
    .then(all { assert(observed == view("scoped", Set("test_one"))), inspect })

  run restartedCacheKeepsAnswersTest = init.then(link("test_two", "alpha")).then(restart).then(edit("beta"))
    .then(all { assert(observed.selected == Set("test_one", "test_two")), inspect })

  run starImportFollowsAllTest = init.then(link("test_two", "star")).then(edit("alpha"))
    .then(all { assert(observed.selected == Set("test_one", "test_two")), inspect })

  run commandLinePluginSelectsEveryTestTest = init.then(edit(PLUGIN))
    .then(all { assert(observed == view("full", TESTS)), inspect })

  run bareTestImportFollowsPrependModeTest = init.then(link("test_one", "helperBare")).then(edit(HELPER))
    .then(all { assert(observed.selected == Set("test_one", "test_sub")), inspect })

  run packageInitEditSelectsItsImportersTest = init.then(edit(INIT))
    .then(all { assert(observed == view("scoped", Set("test_one", "test_two"))), inspect })

  // test_one now reads the table by literal path; the other two already depended on it.
  run literalPathReadTest = init.then(readTable("test_one")).then(edit("table"))
    .then(all { assert(observed == view("full", TESTS)), inspect })

  run sinceStartSpansCommitsTest = init.then(edit("beta")).then(edit("table"))
    .then(all {
      assert(observed == { mode: "scoped", selected: Set("test_two", "test_sub"), sinceStart: { mode: "full", selected: TESTS }, missed: Set() }),
      inspect,
    })
}
