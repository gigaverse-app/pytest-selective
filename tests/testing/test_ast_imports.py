"""Import extraction preserves Python syntax and AST traversal order."""

import ast
import sys
from textwrap import dedent
from unittest.mock import patch

import pytest

from pytest_selective.ast_imports import iter_imports


@pytest.mark.parametrize(
    "source",
    [
        "import first, second as alias\nfrom .sibling import value\nfrom .. import *",
        "import ｆｕｌｌｗｉｄｔｈ\nfrom ｐａｃｋａｇｅ import value",
        "if condition:\n    import yes\nelse:\n    import no",
        "for item in items:\n    import body\nelse:\n    import otherwise",
        "while condition:\n    import body\nelse:\n    import otherwise",
        "with context() as value:\n    import body",
        "def function[T](value: T = default) -> T:\n    import local\n    return value",
        "class Container[T](base):\n    import member\n    def method(self):\n        import local",
        "try:\n    import body\nexcept Error:\n    import handler\nelse:\n    import otherwise\nfinally:\n    import cleanup",
        "try:\n    import body\nexcept* Error:\n    import group_handler\nfinally:\n    import cleanup",
        "match subject:\n    case {'value': value} if condition:\n        import first\n    case _:\n        import second",
        "async def run():\n    async for item in items:\n        import loop\n    async with context():\n        import scoped",
        # Except handlers and match cases add an AST level. Source order and
        # statement-only depth-first traversal would change the finding order.
        dedent("""\
            try:
                import body
            except Error:
                import handler
            finally:
                if condition:
                    import deep_cleanup
            match subject:
                case _:
                    import matched
            def outer():
                import local
                def inner():
                    import nested
            import top_level
        """),
    ],
)
def test_all_imports_keep_ast_walk_order(source: str) -> None:
    if "[T]" in source and sys.version_info < (3, 12):
        pytest.skip("PEP 695 syntax requires a Python 3.12+ parser")
    tree = ast.parse(source)
    expected = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

    assert list(iter_imports(tree)) == expected
    assert expected


def test_import_traversal_work_does_not_grow_with_expression_size() -> None:
    def visited_nodes(expression_size: int) -> int:
        tree = ast.parse(f"values = [{','.join('compute(value)' for _ in range(expression_size))}]\nimport target")
        with patch.object(ast, "iter_child_nodes", wraps=ast.iter_child_nodes) as visit:
            imports = list(iter_imports(tree))
        assert len(imports) == 1
        assert isinstance(imports[0], ast.Import)
        assert imports[0].names[0].name == "target"
        return visit.call_count

    assert visited_nodes(1_000) == visited_nodes(1)
