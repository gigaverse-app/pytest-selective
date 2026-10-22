"""
Why a selection is as large as it is, and whether a change widened the dependency graph.

Selection answers "which tests can this change affect". An explanation answers the questions
an author asks next: which few files funnel most of those tests to the change, whether the
change sits in the startup floor that nearly every test loads, and whether it made some file
reach many more tests than before. Everything is computed from the same immutable snapshots
selection used; nothing here can change which tests run.
"""

from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

from pytest_selective.impact_graph import (
    EdgeEvidence,
    reachable,
    reverse_edges,
    seed_nodes,
    shortest_path,
    union_edges,
    within,
)
from pytest_selective.impact_models import (
    BlastRadiusChange,
    ChangedFileReach,
    EdgeKind,
    FloorChange,
    FloorCycle,
    FloorEntry,
    FloorEntryKind,
    ImpactConfig,
    ImpactReport,
    SelectionExplanation,
    SelectionRoute,
    Snapshot,
    file_of,
)

#: A Python file is in the startup floor when at least this share of test files depend on it.
FLOOR_SHARE = 0.9
#: A file funnels a route when this many selected tests reach the change only through it.
FUNNEL_MIN_TESTS = 8
FUNNEL_MIN_SHARE = 0.2
#: A file's blast radius widened when it gained this many dependent test files.
WIDENED_MIN_TESTS = 20
WIDENED_MIN_SHARE = 0.1
TOP_FUNNELS = 3
NESTED_FUNNELS = 2
TOP_WIDENED = 3
#: Changed files attributed in the explanation, largest share of the selection first.
TOP_CHANGES = 5
#: A floor cycle is reported when it holds at least this many floor files and this share of it.
CYCLE_MIN_FILES = 5
CYCLE_MIN_SHARE = 0.25


def _strongly_connected(nodes: list[str], edges: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's components, iteratively; each is emitted after every component it depends on."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []
    for start in nodes:
        if start in index:
            continue
        work = [(start, iter(edges.get(start, ())))]
        index[start] = low[start] = len(index)
        stack.append(start)
        on_stack.add(start)
        while work:
            node, targets = work[-1]
            advanced = False
            for target in targets:
                if target not in index:
                    index[target] = low[target] = len(index)
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(edges.get(target, ()))))
                    advanced = True
                    break
                if target in on_stack:
                    low[node] = min(low[node], index[target])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)
    return components


def test_bits(snapshot: Snapshot) -> dict[str, int]:
    """Each test file's bit in the masks `dependent_tests` returns: bit i is `snapshot.tests[i]`."""
    return {test: 1 << position for position, test in enumerate(snapshot.tests)}


def dependent_tests(snapshot: Snapshot) -> dict[str, int]:
    """
    For every file, a bitmask of the test files that depend on it (bit i is `snapshot.tests[i]`).

    A file read only as content counts as reached by the tests that read it.
    """
    targets = {target for dependencies in snapshot.edges.values() for target in dependencies}
    nodes = sorted(set(snapshot.edges) | targets | set(snapshot.files))
    components = _strongly_connected(nodes, snapshot.edges)
    owner = {member: position for position, component in enumerate(components) for member in component}
    bits = test_bits(snapshot)
    masks = [0] * len(components)
    # Tarjan emits dependencies first, so the reverse order visits every reader before its targets.
    for position in range(len(components) - 1, -1, -1):
        for member in components[position]:
            masks[position] |= bits.get(member, 0)
        for member in components[position]:
            for target in snapshot.edges.get(member, ()):
                if owner[target] != position:
                    masks[owner[target]] |= masks[position]
    reach: dict[str, int] = {}
    for node, position in owner.items():
        reach[file_of(node)] = reach.get(file_of(node), 0) | masks[position]
    return reach


def startup_floor(snapshot: Snapshot, reach: dict[str, int]) -> set[str]:
    """Non-test Python files that at least `FLOOR_SHARE` of test files depend on."""
    if not snapshot.tests:
        return set()
    threshold = FLOOR_SHARE * len(snapshot.tests)
    tests = set(snapshot.tests)
    return {
        path
        for path in snapshot.files
        if path.endswith(".py") and path not in tests and reach.get(path, 0).bit_count() >= threshold
    }


def _dominators(root: str, successors: Mapping[str, Iterable[str]]) -> dict[str, str]:
    """Immediate dominators of every node reachable from `root` (Cooper, Harvey and Kennedy)."""
    order: list[str] = []
    seen = {root}
    work = [(root, iter(sorted(successors.get(root, ()))))]
    while work:
        node, children = work[-1]
        child = next(children, None)
        if child is None:
            order.append(node)
            work.pop()
        elif child not in seen:
            seen.add(child)
            work.append((child, iter(sorted(successors.get(child, ())))))
    postorder = {node: position for position, node in enumerate(order)}
    predecessors: dict[str, list[str]] = {node: [] for node in order}
    for node in order:
        for child in successors.get(node, ()):
            predecessors[child].append(node)
    idom = {root: root}
    changed = True
    while changed:
        changed = False
        for node in reversed(order):
            if node == root:
                continue
            candidates = [pred for pred in predecessors[node] if pred in idom]
            new = candidates[0]
            for pred in candidates[1:]:
                a, b = pred, new
                while a != b:
                    while postorder[a] < postorder[b]:
                        a = idom[a]
                    while postorder[b] < postorder[a]:
                        b = idom[b]
                new = a
            if idom.get(node) != new:
                idom[node] = new
                changed = True
    return idom


def _bits_of(reach: dict[str, int], paths: Iterable[str]) -> int:
    mask = 0
    for path in paths:
        mask |= reach.get(path, 0)
    return mask


def _funnels(
    reverse: dict[str, list[str]], seeds: list[str], reached: list[str], tests: list[str]
) -> list[SelectionRoute]:
    """
    Files every path from the change to many reached tests passes through, largest first.

    Dominators of the reverse graph, rooted at the change: a test's dominator chain is exactly
    the files it cannot reach the change without. Each funnel nests inside the nearest enclosing
    funnel on that chain, which is the one closer to the change.
    """
    root = "<change>"
    idom = _dominators(root, {**reverse, root: sorted(seed_nodes(seeds))})
    counts: dict[str, int] = {}
    for test in reached:
        node = idom[test]
        while node != root:
            counts[node] = counts.get(node, 0) + 1
            node = idom[node]
    excluded = seed_nodes(seeds) | set(tests)
    threshold = max(FUNNEL_MIN_TESTS, FUNNEL_MIN_SHARE * len(reached))
    funnels = {node for node, count in counts.items() if count >= threshold and node not in excluded}

    def enclosing(node: str) -> str | None:
        ancestor = idom[node]
        while ancestor != root:
            if ancestor in funnels:
                return ancestor
            ancestor = idom[ancestor]
        return None

    parents = {funnel: enclosing(funnel) for funnel in funnels}
    ranked = sorted(funnels, key=lambda node: (-counts[node], node))
    routes: list[SelectionRoute] = []
    for funnel in [node for node in ranked if parents[node] is None][:TOP_FUNNELS]:
        routes.append(SelectionRoute(kind="funnel", tests=counts[funnel], via=file_of(funnel)))
        for inner in [node for node in ranked if parents[node] == funnel][:NESTED_FUNNELS]:
            routes.append(
                SelectionRoute(kind="funnel", tests=counts[inner], via=file_of(inner), parent=file_of(funnel))
            )
    return routes


def _routes(
    edges: dict[str, list[str]],
    seeds: list[str],
    selected: list[str],
    floor_seeds: list[str],
    reach: dict[str, int],
    after: Snapshot,
) -> list[SelectionRoute]:
    """Group the selected tests by how they reach the change; top-level routes partition them."""
    reverse = reverse_edges(edges)
    reachable_nodes = reachable(reverse, seed_nodes(seeds))
    reached = [test for test in selected if test in reachable_nodes]
    routes: list[SelectionRoute] = []
    if floor_seeds:
        floor_mask, bits = _bits_of(reach, floor_seeds), test_bits(after)
        routes.append(SelectionRoute(kind="floor", tests=sum(1 for test in reached if floor_mask & bits[test])))
    else:
        seed_set = set(seeds)
        if edited := sum(1 for test in reached if test in seed_set):
            routes.append(SelectionRoute(kind="changed", tests=edited))
        routes += _funnels(reverse, seeds, reached, after.tests)
    if remaining := len(reached) - sum(route.tests for route in routes if route.parent is None):
        routes.append(SelectionRoute(kind="other", tests=remaining))
    if len(selected) > len(reached):
        routes.append(SelectionRoute(kind="unreached", tests=len(selected) - len(reached)))
    return routes


def _startup_roots(snapshot: Snapshot) -> list[str]:
    """Files at least `FLOOR_SHARE` of test files depend on directly: the floor's entry points."""
    counts: dict[str, int] = {}
    tests = set(snapshot.tests)
    for test in snapshot.tests:
        for dependency in snapshot.edges.get(test, ()):
            if file_of(dependency) not in tests:
                counts[dependency] = counts.get(dependency, 0) + 1
    return sorted(node for node, count in counts.items() if count >= FLOOR_SHARE * len(snapshot.tests))


def _entry_kind(path: str, edge: EdgeKind | None) -> FloorEntryKind:
    """What a test's direct edge to a floor entry says about how to shrink what the entry loads."""
    name = PurePosixPath(path).name
    if name == "__init__.py":
        return "package"
    if edge == "conftest":
        return "conftest"
    if edge == "startup":
        return "hooks" if name == "conftest.py" else "startup"
    if edge in {"import", "string"}:
        return "import"
    return "declared"


def _floor_entries(snapshot: Snapshot, roots: list[str], floor: set[str], evidence: EdgeEvidence) -> list[FloorEntry]:
    """
    Each startup root as a file, how tests load it, and its floor share.

    The edge is read from a test outside the root's directory when there is one: a conftest its
    own descendants load is an ancestor to them, and only an outside reader shows its hooks made
    it global.
    """
    entries: dict[str, FloorEntry] = {}
    for root in roots:
        path = file_of(root)
        readers = [test for test in snapshot.tests if root in snapshot.edges.get(test, ())]
        reader = _reader_outside(snapshot, path, readers)
        pulled = {file_of(node) for node in reachable(snapshot.edges, {root})} & floor
        entry = FloorEntry(path=path, kind=_entry_kind(path, evidence.step(reader, root).kind), floor_files=len(pulled))
        if path not in entries or entry.floor_files > entries[path].floor_files:
            entries[path] = entry
    return sorted(entries.values(), key=lambda entry: (-entry.floor_files, entry.path))


def _floor_cycle(snapshot: Snapshot, floor: set[str]) -> FloorCycle | None:
    """The floor's largest import cycle, when it holds enough of the floor to be the thing to fix."""
    inside = {path: [target for target in snapshot.edges.get(path, ()) if target in floor] for path in floor}
    largest = set(max(_strongly_connected(sorted(floor), inside), key=len, default=[]))
    if len(largest) < max(CYCLE_MIN_FILES, CYCLE_MIN_SHARE * len(floor)):
        return None
    readers: dict[str, int] = {}
    for member in largest:
        for target in inside[member]:
            if target in largest:
                readers[target] = readers.get(target, 0) + 1
    hub = min(readers, key=lambda path: (-readers[path], path))
    return FloorCycle(size=len(largest), hub=hub, hub_readers=readers[hub])


def _reader_outside(snapshot: Snapshot, path: str, readers: list[str]) -> str:
    """A test that loads `path` from outside its directory when there is one, else the first."""
    directory = str(PurePosixPath(path).parent)
    return next((test for test in readers if not within(test, directory)), readers[0])


def _changed_reach(
    snapshot: Snapshot,
    seeds: list[str],
    selected: list[str],
    reach: dict[str, int],
    roots: list[str],
    evidence: EdgeEvidence,
) -> list[ChangedFileReach]:
    """
    Attribute the selection to the changed files: how many selected tests load each one, and how.

    A test can load several changed files, so the counts overlap; each says what that file alone
    selects. Hubs are searched without the startup floor: every test depends on its entries, so
    naming one would say nothing about this change.
    """
    bits = test_bits(snapshot)
    chosen = sum(bits[test] for test in selected if test in bits)
    shares = sorted(((reach.get(seed, 0) & chosen).bit_count(), seed) for seed in seeds if reach.get(seed, 0) & chosen)[
        ::-1
    ][:TOP_CHANGES]
    if not shares:
        return []
    entries = set(roots)
    own_edges = {reader: [] if reader in entries else list(deps) for reader, deps in snapshot.edges.items()}
    own_snapshot = snapshot.model_copy(update={"edges": own_edges})
    assert isinstance(own_snapshot, Snapshot)
    own_reach = dependent_tests(own_snapshot)
    reverse = reverse_edges(own_edges)
    attributed = []
    for count, seed in shares:
        loaders = [test for test in selected if bits.get(test, 0) & own_reach.get(seed, 0)]
        nodes = seed_nodes([seed])
        direct = [test for test in loaders if nodes & set(snapshot.edges.get(test, ()))]
        ancestors = reachable(reverse, nodes) - nodes
        hubs: dict[str, list[str]] = {}
        for test in loaders:
            if test in direct:
                continue
            for dependency in snapshot.edges.get(test, ()):
                if dependency in ancestors and dependency not in entries and file_of(dependency) not in bits:
                    hubs.setdefault(dependency, []).append(test)
        entry = ChangedFileReach(path=seed, tests=count, direct=len(direct), own=len(loaders))
        if hubs:
            hub = min(hubs, key=lambda node: (-len(hubs[node]), node))
            reader = _reader_outside(snapshot, file_of(hub), hubs[hub])
            kind = _entry_kind(file_of(hub), evidence.step(reader, hub).kind)
            entry = entry.model_copy(update={"hub": file_of(hub), "hub_tests": len(hubs[hub]), "hub_kind": kind})
        attributed.append(entry)
    return attributed


def _mask(snapshot: Snapshot, tests: set[str]) -> int:
    return sum(bit for test, bit in test_bits(snapshot).items() if test in tests)


def _widened(
    before: Snapshot, after: Snapshot, reach_before: dict[str, int], reach_after: dict[str, int], floor_added: set[str]
) -> list[tuple[str, int, int]]:
    """
    Files that more existing test files depend on than before.

    Only test files present in both trees count: a PR that adds tests importing a module did not
    widen the graph, it tested more.
    """
    threshold = max(WIDENED_MIN_TESTS, WIDENED_MIN_SHARE * len(after.tests))
    common = set(before.tests) & set(after.tests)
    common_before, common_after = _mask(before, common), _mask(after, common)
    after_tests = set(after.tests)
    rows = []
    for path in after.files.keys() & before.files.keys():
        if not path.endswith(".py") or path in after_tests or path in floor_added:
            continue
        old = (reach_before.get(path, 0) & common_before).bit_count()
        new = (reach_after.get(path, 0) & common_after).bit_count()
        if new - old >= threshold:
            rows.append((path, old, new))
    return sorted(rows, key=lambda row: (row[1] - row[2], row[0]))[:TOP_WIDENED]


def _cause(before: Snapshot, after: Snapshot, changed: set[str], target: str) -> list[str]:
    """A dependency this change added, from a changed file, whose target leads to `target`."""
    for reader in sorted(changed):
        added = sorted(set(after.edges.get(reader, ())) - set(before.edges.get(reader, ())))
        for dependency in added:
            onward = shortest_path(after.edges, [dependency], seed_nodes([target]))
            if onward:
                return [reader, *onward]
    return []


def explain(
    repo: Path,
    before: Snapshot,
    after: Snapshot,
    report: ImpactReport,
    config: ImpactConfig,
    *,
    graph_before: Snapshot | None = None,
    forced_full: bool = False,
) -> SelectionExplanation:
    """
    Explain `report`, which selection produced from `before` and `after`.

    Routes follow the selection itself. Floor and widening deltas compare `after` with
    `graph_before`, the PR's merge base, when there is one: selection may have started from a tree
    an earlier push already validated, which would make a graph change vanish after that push.
    """
    graph_before = graph_before or before
    reach_after, reach_before = dependent_tests(after), dependent_tests(graph_before)
    floor_after, floor_before = startup_floor(after, reach_after), startup_floor(graph_before, reach_before)
    floor_seeds = sorted(set(report.seeds) & floor_after)
    roots = _startup_roots(after)
    evidence = EdgeEvidence(repo, after, config)
    added = sorted(floor_after - floor_before)
    changed = set(report.changed)
    explanation = SelectionExplanation(
        base=report.base,
        head=report.head,
        selected=len(report.selected),
        total=report.total_files,
        forced_full=forced_full,
        graph_base=graph_before.tree,
        floor_seeds=floor_seeds,
        routes=_routes(union_edges(before, after), report.seeds, report.selected, floor_seeds, reach_after, after),
        floor=FloorChange(
            share=FLOOR_SHARE,
            before=len(floor_before),
            after=len(floor_after),
            added=added,
            removed=sorted(floor_before - floor_after),
            path=evidence.path(shortest_path(after.edges, roots, set(added)) if added else []),
            files=sorted(floor_after),
            entries=_floor_entries(after, roots, floor_after, evidence),
            cycle=_floor_cycle(after, floor_after),
        ),
        changes=_changed_reach(after, report.seeds, report.selected, reach_after, roots, evidence),
        widened=[
            BlastRadiusChange(
                path=file, before=old, after=new, cause=evidence.path(_cause(graph_before, after, changed, file))
            )
            for file, old, new in _widened(graph_before, after, reach_before, reach_after, set(added))
        ],
    )
    if floor_seeds:
        # A changed root explains nothing about how the rest of the change entered the floor.
        beyond_roots = [seed for seed in floor_seeds if seed not in roots] or floor_seeds
        route_path = shortest_path(after.edges, roots, seed_nodes(beyond_roots))
    elif (funnel := explanation.top_funnel) is not None and funnel.via is not None:
        route_path = shortest_path(after.edges, [funnel.via], seed_nodes(report.seeds))
    else:
        route_path = []
    return explanation.model_copy(update={"path": evidence.path(route_path)})
