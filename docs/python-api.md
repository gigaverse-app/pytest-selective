# Supported Python API

Prefer the pytest plugin, `pytest-selective-impact` and the published actions. When
another tool or a repository's own CI checks need Python, import only the names
below. Each one is imported by an adopter (CI-esta, or the gigaverse AI, backend
and mobile repositories), and `tests/test_python_api.py` imports every name in
this table, so removing or renaming one fails CI. Any other module or name is
internal and can change in any release.

The portable declaration parser has its own package and contract:
[`selective-deps`](../declarations/README.md).

## Stability rules

- Removing or renaming a name below is a breaking change (`feat!`). Keep the old
  name as an alias for at least one minor release first, and list it under
  **Deprecated** with its replacement.
- Changing what a function selects or reports for an unchanged repository is a
  `feat`, never a `fix`, even when the old answer was wrong, and its PR body says
  what adopters should run or check.
- Adding a name here requires an adopter that imports it.

## Selection and graphs

| Module | Names |
| --- | --- |
| `pytest_selective.impact_models` | `ImpactConfig`, `ImpactReport`, `Snapshot`, `GitTree`, `NameScopedModule`, `contents_node`, `SelectionExplanation`, `ExplanationUnavailable`, `ChangedFileReach`, `FloorEntry`, `FloorEntryKind`, `PathStep`, `SelectionRoute` |
| `pytest_selective.impact_selection` | `affected`, `base_snapshot` |
| `pytest_selective.impact_graph` | `GraphCache`, `ModuleIndex`, `DependencyDeclarationError`, `declared_inputs`, `dependency_comment`, `explanation`, `git`, `git_environment`, `inventory`, `matches`, `parse_source`, `policy_fingerprints`, `reachable`, `resolve_graph`, `reverse_edges`, `seed_nodes`, `union_edges`, `within` |
| `pytest_selective.impact_name_scope` | `NotNarrowed`, `changed_names`, `externally_read`, `externally_read_names`, `named_readers` |
| `pytest_selective.impact_cli` | `main` |
| `pytest_selective.ast_imports` | `import_candidates`, `iter_imports`, `module_file`, `normalized_name`, `parse_ast` |
| `pytest_selective.input_policy` | `DEFAULT_GLOBAL_INPUTS` |
| `pytest_selective.git_operations` | `pull_request_merge_base` |
| `pytest_selective.test_inventory` | `DEFAULT_TEST_FILE_PATTERNS`, `TEST_FILE_PATTERNS`, `is_test_file`, `is_test_module_name` |

## CI lanes and checkpoints

| Module | Names |
| --- | --- |
| `pytest_selective.ci` | `Lane`, `LaneConfig`, `LanePlan`, `plan` |
| `pytest_selective.checkpoint` | `full_checkpoint_reason` |
| `pytest_selective.pytest_sharding` | `load_durations`, `merge_duration_files`, `plan_shard_count`, `plan_shards`, `write_shard_files` |

## Hygiene and expansion

| Module | Names |
| --- | --- |
| `pytest_selective.hygiene` | `TestImportViolation`, `assert_test_file_isolation`, `discover_test_modules`, `find_test_import_violations`, `is_test_module` |
| `pytest_selective.pytest_expansion` | `ACTIVATION`, `MARKER`, `MODULE_DECLARATIONS`, `PYTHON_SOURCES`, `SCOPES`, `Declaration`, `DeclarationKey`, `Expansion`, `LocatedDeclaration`, `Renames`, `SourceTree`, `Surface`, `check`, `expansions`, `git`, `git_environment`, `inspect_source`, `main`, `module_nodes`, `moved_packages`, `protected`, `reason_before`, `surfaces`, `within`, `worktree_snapshot` |

## Deprecated

None.
