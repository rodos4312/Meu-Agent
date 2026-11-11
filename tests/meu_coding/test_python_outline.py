"""The fast-index scanner must agree with the stdlib AST on definitions and imports."""

from meu_coding.interfaces import FAST
from meu_coding.python_outline import PythonOutlineScanner
from meu_coding.symbols import PythonASTFallback

SOURCE = '''\
"""Module docstring mentioning
def not_a_function():
import not_an_import
"""
from __future__ import annotations

import os, sys as system
from .sibling import (
    alpha,
    beta as b,  # comment
)
from pkg.sub import gamma, \\
    delta

LIMIT: int = 3
TABLE = {
    "key": "def fake(): pass",
    "other": (1, 2),
}


@decorator(
    option=True,
)
class Store(Base):
    """class docstring
    def ghost(self): ...
    """

    def get(self, key: str) -> str:
        from late.module import thing
        text = "(unbalanced"
        return text

    async def put(
        self,
        key,
    ):
        def inner():
            return 1
        return inner


def top_level():
    return Store()


if __name__ == "__main__":
    MAIN_FLAG = True
'''


def _defs(result):
    return [(s.name, s.kind, s.line, s.container) for s in result.definitions]


def _imports(result):
    return [(s.name, s.container, s.line) for s in result.imports]


def test_outline_definitions_match_the_ast():
    fast = PythonOutlineScanner().extract("m.py", SOURCE, "python")
    deep = PythonASTFallback().extract("m.py", SOURCE, "python")
    assert fast.depth == FAST
    assert _defs(fast) == _defs(deep)


def test_outline_imports_match_the_ast_including_late_and_multiline():
    fast = PythonOutlineScanner().extract("m.py", SOURCE, "python")
    deep = PythonASTFallback().extract("m.py", SOURCE, "python")
    assert _imports(fast) == _imports(deep)


def test_outline_end_lines_close_blocks():
    fast = {s.name: s for s in PythonOutlineScanner().extract("m.py", SOURCE, "python").definitions}
    deep = {s.name: s for s in PythonASTFallback().extract("m.py", SOURCE, "python").definitions}
    for name in ("Store", "get", "put", "inner", "top_level"):
        assert fast[name].end_line == deep[name].end_line, name


def test_outline_never_raises_on_garbage():
    result = PythonOutlineScanner().extract("g.py", "\x00 def (((\n'''\nclass", "python")
    assert result.error is None


TRICKY = '''\
"""Docstring with an open bracket (never closed
and a second line."""
from __future__ import annotations

SQL = """
    SELECT 1 WHERE x = """ + PART + """
    AND y = 2
"""
MARKERS = ('"""', "x")
A = B = None


class Holder:
    def answer(self):
        return json_response({
"status": "ok", "late": "column zero inside brackets",
        })

    def after(self):
        import late_module
        return late_module
'''


def test_outline_survives_strings_brackets_and_column_zero_continuations():
    fast = PythonOutlineScanner().extract("t.py", TRICKY, "python")
    deep = PythonASTFallback().extract("t.py", TRICKY, "python")
    assert _defs(fast) == _defs(deep)
    assert _imports(fast) == _imports(deep)
