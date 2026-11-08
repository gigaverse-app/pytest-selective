// What pytest-selective promises about one small repository, commit after commit.
//
// After each commit, the selected tests are exactly the tests that reach a changed file
// through imports, an ancestor conftest or a declared read, in the base or the head tree.
// A change to a global input selects every test. `event` names each commit for the driver;
// `observed` is the selection the driver must read back from the real planner.
module selection {
  type Event = { op: str, file: str, target: str }
  type View = { mode: str, selected: Set[str] }

  pure val MODULES = Set("alpha", "beta", "gamma")
  pure val TESTS = Set("test_one", "test_two")
  // Files that can import a module.
  pure val IMPORTERS = MODULES.union(TESTS).union(Set("conftest"))
  // Every file in the graph: the importers and a data table that test_two declares it reads.
  pure val FILES = IMPORTERS.union(Set("table"))
  // Files a commit may delete and add back.
  pure val REMOVABLE = MODULES.union(TESTS)

  // Imports each file's source spells, including imports of a module that is currently deleted.
  var imports: Set[(str, str)]
  var present: Set[str]
  var event: Event
  var observed: View

  // The dependency edges of one tree: imports between files that exist, each test's
  // ancestor conftest, and test_two's declared read of the table.
  pure def edges(spelled: Set[(str, str)], files: Set[str]): Set[(str, str)] = {
    val resolved = spelled.filter(e => files.contains(e._1) and files.contains(e._2))
    val conftest = if (files.contains("conftest")) TESTS.intersect(files).map(t => (t, "conftest")) else Set()
    val declared = if (files.contains("test_two")) Set(("test_two", "table")) else Set()
    resolved.union(conftest).union(declared)
  }

  // The files that reach `changed` along `e`, the changed files included. Folding once per file
  // is enough steps to follow any path between them.
  pure def reaching(e: Set[(str, str)], changed: Set[str]): Set[str] =
    FILES.fold(changed, (found, _) => found.union(e.filter(x => found.contains(x._2)).map(x => x._1)))

  pure def selection(
    beforeImports: Set[(str, str)], beforeFiles: Set[str],
    afterImports: Set[(str, str)], afterFiles: Set[str],
    changed: Set[str], global: bool,
  ): View = {
    val tests = TESTS.intersect(afterFiles)
    val both = edges(beforeImports, beforeFiles).union(edges(afterImports, afterFiles))
    val chosen = if (global) tests else reaching(both, changed).intersect(tests)
    {
      mode: if (global or (chosen.size() > 0 and chosen == tests)) "full" else if (chosen.size() > 0) "scoped" else "none",
      selected: chosen,
    }
  }

  // One commit from the current tree to the given one, and the selection between them.
  action commit(
    op: str, file: str, target: str,
    nextImports: Set[(str, str)], nextFiles: Set[str], changed: Set[str], global: bool,
  ): bool = all {
    imports' = nextImports,
    present' = nextFiles,
    event' = { op: op, file: file, target: target },
    observed' = selection(imports, present, nextImports, nextFiles, changed, global),
  }

  action init = all {
    imports' = Set(("test_one", "alpha"), ("alpha", "beta"), ("test_two", "gamma")),
    present' = FILES,
    event' = { op: "init", file: "", target: "" },
    observed' = { mode: "none", selected: Set() },
  }

  // Change a file's body without changing what it imports.
  action edit(file: str): bool = all {
    present.contains(file),
    commit("edit", file, "", imports, present, Set(file), false),
  }

  action link(file: str, target: str): bool = all {
    IMPORTERS.contains(file),
    MODULES.contains(target),
    file != target,
    present.contains(file),
    present.contains(target),
    not(imports.contains((file, target))),
    commit("link", file, target, imports.union(Set((file, target))), present, Set(file), false),
  }

  action unlink(file: str, target: str): bool = all {
    present.contains(file),
    imports.contains((file, target)),
    commit("unlink", file, target, imports.exclude(Set((file, target))), present, Set(file), false),
  }

  // Delete a file. Its importers keep spelling the import, which no longer resolves.
  action remove(file: str): bool = all {
    REMOVABLE.contains(file),
    present.contains(file),
    commit("remove", file, "", imports.filter(e => e._1 != file), present.exclude(Set(file)), Set(file), false),
  }

  // Add a deleted file back, importing nothing.
  action restore(file: str): bool = all {
    REMOVABLE.contains(file),
    not(present.contains(file)),
    commit("restore", file, "", imports, present.union(Set(file)), Set(file), false),
  }

  action touchGlobal = commit("touchGlobal", "", "", imports, present, Set(), true)

  // A step that commits nothing, so that a witness can end in an assertion.
  action inspect = all {
    imports' = imports,
    present' = present,
    event' = { op: "inspect", file: "", target: "" },
    observed' = observed,
  }

  action step = {
    nondet file = FILES.oneOf()
    nondet target = MODULES.oneOf()
    any { edit(file), link(file, target), unlink(file, target), remove(file), restore(file), touchGlobal }
  }

  val selectsOnlyExistingTests = observed.selected.subseteq(TESTS.intersect(present))

  run transitiveEditTest = init.then(edit("beta"))
    .then(all { assert(observed == { mode: "scoped", selected: Set("test_one") }), inspect })

  run deletedModuleSelectsFormerImportersTest = init.then(remove("beta"))
    .then(all { assert(observed == { mode: "scoped", selected: Set("test_one") }), inspect })

  run declaredReadTest = init.then(edit("table"))
    .then(all { assert(observed == { mode: "scoped", selected: Set("test_two") }), inspect })

  run conftestSelectsEveryTestTest = init.then(edit("conftest"))
    .then(all { assert(observed == { mode: "full", selected: TESTS }), inspect })

  run globalInputSelectsEveryTestTest = init.then(touchGlobal)
    .then(all { assert(observed == { mode: "full", selected: TESTS }), inspect })

  run newImportWidensSelectionTest = init.then(link("test_two", "alpha")).then(edit("beta"))
    .then(all { assert(observed == { mode: "full", selected: TESTS }), inspect })

  run deletedTestIsNotSelectedTest = init.then(remove("test_one")).then(edit("beta"))
    .then(all { assert(observed == { mode: "none", selected: Set() }), inspect })
}
