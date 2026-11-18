# selective-deps

Declare file dependencies for test selection and incremental tooling in any language:

```sh
pip install selective-deps
```

This package installs Pydantic and PyYAML. It does not depend on pytest or
pytest-selective, register plugins, inspect Python imports, open a graph cache,
or run Git. The full pytest-selective package uses this same implementation.

Place a sidecar next to the code that reads an input, for example
`web/catalog.ts.gv-dependency.yaml`:

```yaml
dependencies:
  - inputs: ["//fixtures/catalog/*.json"]
    kind: content
    reason: The catalog loader reads these files at runtime.
```

Use `.gv-dependencies.yaml` for several readers in one directory, adding
`readers: ["*.ts"]` to each rule. Paths are relative to the manifest directory;
`//` anchors a path at the repository root. `relative_to: reader` resolves
unanchored inputs relative to each reader instead. `*`, `?` and whole-segment
`**` patterns use the same validation as Python declarations.

Prefer one directory manifest to a sidecar per file. In a manifest, `{stem}` in
an input is each reader's file name before its first dot, so
`inputs: ["{stem}.mjs"]` pairs `report.test.mjs` with `report.mjs`. A rule with
`inputs: []` records readers reviewed as having no repository inputs, such as
scripts that read only generated reports; it requires a `reason`. Use `reason`
rather than YAML comments to explain any rule.

The adapter supplies a complete tracked-file inventory and the declaration bytes
from one snapshot:

```python
from selective_deps import dependency_edges

files = {"web/catalog.ts", "web/catalog.ts.gv-dependency.yaml", "fixtures/catalog/demo.json"}
manifests = {
    "web/catalog.ts.gv-dependency.yaml": b"dependencies:\n  - inputs: ['//fixtures/catalog/*.json']\n    kind: content\n"
}
edges = dependency_edges(manifests, files, revision="checked-out-commit")
```

The result maps readers to dependencies. `kind: import` creates ordinary path
nodes whose transitive imports the language adapter should follow. `kind: content`
creates `@contents:<path>` leaf nodes: reading a source file as text does not
execute its imports. `contents_node(path)` and `file_of(node)` expose these
semantics without requiring a caller to reproduce the encoding.

Combine these edges with the native language graph before traversing it. A changed
file affects both its ordinary path node and its content node. Include base and
head graphs when handling removals. Manifest files themselves are dependencies
of their readers, so changing a declaration also selects those readers.

Malformed YAML, duplicate keys, aliases, missing owners, unmatched patterns and
an incomplete declaration inventory raise `DependencyDeclarationError`. Report
that error rather than treating a partial graph as proof to skip work. Declaration
parsing does not discover undeclared runtime reads or prove test completion.
