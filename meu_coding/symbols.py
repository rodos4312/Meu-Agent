"""Symbol extraction with layered backends that never take the whole analysis down.

Two depths (``interfaces.FAST`` / ``interfaces.DEEP``):

* **fast**: every file at index time. ``PythonOutlineScanner`` for Python (no parser),
  ``LightweightFallback`` regexes for other languages. Definitions and imports only.
* **deep**: files that become relevant, in order until one succeeds:
  1. ``PythonASTFallback``: the stdlib parser is exact and gives containers and end lines.
     ``ast.parse`` only parses; it never runs the code.
  2. ``TreeSitterExtractor`` when ``tree_sitter_language_pack`` is importable (optional, no
     dependency is added): other languages, and Python files the AST cannot parse.
  3. ``LightweightFallback``: line regexes, tolerant of any input.

A backend that raises is recorded as the result's ``error`` and the next one is tried.

Deep Python extraction keeps only high-value references (see ``_PythonVisitor``): names
imported into the file, attribute chains rooted at an imported module, and names the
file itself defines. Locals, parameters, builtins and attributes of arbitrary objects are
dropped; they were most of all symbols and never linked to a definition.
"""

from __future__ import annotations

import ast
import importlib
import logging
import re
from collections.abc import Callable, Iterable

from meu_coding.interfaces import DEEP, FAST, ExtractionResult, Symbol
from meu_coding.python_outline import PythonOutlineScanner

logger = logging.getLogger(__name__)


class PythonASTFallback:
    name = "python-ast"

    def __init__(self, keep_low_references: bool = False) -> None:
        self.keep_low_references = keep_low_references

    def supports(self, language: str) -> bool:
        return language == "python"

    def extract(self, path: str, source: str, language: str) -> ExtractionResult:
        tree = ast.parse(source, filename=path)
        visitor = _PythonVisitor(path)
        visitor.visit(tree)
        return ExtractionResult(path, tuple(visitor.finish(self.keep_low_references)), self.name)


def _chain_root(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


class _PythonVisitor(ast.NodeVisitor):
    """Definitions and imports as found; references collected raw and tiered in ``finish``:

    * HIGH: a name bound by an import in this file (recorded under the imported name, so
      ``from x import helper as h; h()`` references ``helper``), or an attribute of a chain
      rooted at such a name (``mod.func()``, ``pkg.sub.Class``);
    * MEDIUM: a name or attribute this file defines (``helper()``, ``self.method()``);
    * LOW: everything else (locals, parameters, builtins, attributes of other objects),
      dropped unless ``keep_low``.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.symbols: list[Symbol] = []
        self._stack: list[tuple[str, str]] = []  # (name, kind)
        self._bindings: dict[str, str] = {}  # local name -> imported name (or module root)
        self._raw_refs: list[tuple[str, str | None, int, int, str | None]] = []
        self._seen_refs: set[tuple[str, str | None]] = set()

    def _container(self) -> str | None:
        return ".".join(name for name, _ in self._stack) or None

    def _add(self, name: str, kind: str, node: ast.AST, container: str | None = None) -> None:
        self.symbols.append(Symbol(
            name, kind, self.path, node.lineno, "python", node.col_offset, container,
            getattr(node, "end_lineno", None),
        ))

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._add(node.name, "class", node, self._container())
        self._stack.append((node.name, "class"))
        self.generic_visit(node)
        self._stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        in_class = bool(self._stack) and self._stack[-1][1] == "class"
        self._add(node.name, "method" if in_class else "function", node, self._container())
        self._stack.append((node.name, "function"))
        self.generic_visit(node)
        self._stack.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name, "import", node)
            bound = alias.asname or alias.name.split(".")[0]
            self._bindings[bound] = bound

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            self._add(module, "import", node, container=alias.name)
            if alias.name != "*":
                self._bindings[alias.asname or alias.name] = alias.name

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self._stack:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._add(target.id, "variable", node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self._stack and isinstance(node.target, ast.Name):
            self._add(node.target.id, "variable", node)
        self.generic_visit(node)

    def _reference(self, name: str, node: ast.AST, root: str | None) -> None:
        container = self._container()
        if (name, container) not in self._seen_refs:
            self._seen_refs.add((name, container))
            self._raw_refs.append((name, container, node.lineno, node.col_offset, root))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._reference(node.id, node, None)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self._reference(node.attr, node, _chain_root(node.value) or "")
        self.generic_visit(node)

    def finish(self, keep_low: bool = False) -> list[Symbol]:
        defined = {s.name for s in self.symbols if s.is_definition}
        for name, container, line, column, root in self._raw_refs:
            target = self._tier_target(name, root, defined, keep_low)
            if target is not None:
                self.symbols.append(Symbol(target, "reference", self.path, line, "python", column, container))
        return self.symbols

    def _tier_target(self, name: str, root: str | None, defined: set[str], keep_low: bool) -> str | None:
        if root is None:  # a bare name: HIGH via an import binding, MEDIUM if defined here
            if name in self._bindings:
                return self._bindings[name]
            return name if name in defined or keep_low else None
        if root in self._bindings or name in defined or keep_low:
            return name
        return None


# ── tree-sitter (optional) ───────────────────────────────────────────────────

_TS_DEFINITIONS = {
    "class_definition": "class", "class_declaration": "class", "class_specifier": "class",
    "struct_item": "class", "struct_specifier": "class", "enum_item": "class",
    "trait_item": "class", "interface_declaration": "class", "type_spec": "class",
    "function_definition": "function", "function_declaration": "function",
    "function_item": "function", "method_definition": "method",
    "method_declaration": "method", "generator_function_declaration": "function",
}
_TS_IMPORTS = frozenset({
    "import_statement", "import_from_statement", "import_declaration", "use_declaration",
    "preproc_include", "import_spec",
})
_TS_CLASS_KINDS = frozenset({"class"})


def _load_language_pack() -> Callable[[str], object] | None:
    try:
        module = importlib.import_module("tree_sitter_language_pack")
    except ImportError:
        return None
    return getattr(module, "get_parser", None)


class TreeSitterExtractor:
    """Generic tree walk: named definition nodes and import statements.

    ``parser_factory(language)`` returns an object with ``parse(bytes)``; by default it comes
    from ``tree_sitter_language_pack`` when that package is installed.
    """

    name = "tree-sitter"

    def __init__(self, parser_factory: Callable[[str], object] | None = None) -> None:
        self._factory = parser_factory if parser_factory is not None else _load_language_pack()
        self._parsers: dict[str, object | None] = {}

    @property
    def available(self) -> bool:
        return self._factory is not None

    def _parser(self, language: str) -> object | None:
        if language not in self._parsers:
            try:
                self._parsers[language] = self._factory(language) if self._factory else None
            except Exception:  # an unknown grammar is "unsupported", not a failure
                logger.debug("no tree-sitter grammar for %s", language, exc_info=True)
                self._parsers[language] = None
        return self._parsers[language]

    def supports(self, language: str) -> bool:
        return self.available and self._parser(language) is not None

    def extract(self, path: str, source: str, language: str) -> ExtractionResult:
        data = source.encode("utf-8")
        tree = self._parser(language).parse(data)  # type: ignore[union-attr]
        symbols: list[Symbol] = []
        self._walk(tree.root_node, path, language, data, [], symbols)
        return ExtractionResult(path, tuple(symbols), self.name)

    def _walk(self, node, path: str, language: str, data: bytes, stack: list[str],
              out: list[Symbol]) -> None:
        kind = _TS_DEFINITIONS.get(node.type)
        pushed = False
        if kind is not None:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = data[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
                if kind == "function" and stack:
                    kind = "method"
                out.append(_ts_symbol(name, kind, path, language, node, ".".join(stack) or None))
                if kind in _TS_CLASS_KINDS:
                    stack.append(name)
                    pushed = True
        elif node.type in _TS_IMPORTS:
            text = data[node.start_byte:node.end_byte].decode("utf-8", "replace")
            for module in _import_targets(text):
                out.append(_ts_symbol(module, "import", path, language, node, None))
        for child in node.children:
            self._walk(child, path, language, data, stack, out)
        if pushed:
            stack.pop()


def _ts_symbol(name: str, kind: str, path: str, language: str, node, container: str | None) -> Symbol:
    (row, col), (end_row, _) = node.start_point, node.end_point
    return Symbol(name, kind, path, row + 1, language, col, container, end_row + 1)


_QUOTED = re.compile(r"""["'<]([^"'<>]+)["'>]""")


def _import_targets(statement: str) -> list[str]:
    quoted = _QUOTED.findall(statement)
    if quoted:
        return quoted
    match = re.match(r"\s*(?:use|import|from)\s+([\w.:]+)", statement)
    return [match.group(1)] if match else []


# ── lightweight regex fallback ───────────────────────────────────────────────

_RX = re.compile
_PATTERNS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "python": (
        ("class", _RX(r"^\s*class\s+([A-Za-z_]\w*)")),
        ("function", _RX(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")),
        ("import", _RX(r"^\s*import\s+([\w.]+)")),
        ("import", _RX(r"^\s*from\s+(\.*[\w.]*)\s+import\b")),
    ),
    "javascript": (
        ("class", _RX(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
        ("function", _RX(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)")),
        ("function", _RX(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
        ("import", _RX(r"""^\s*import\b[^'"]*['"]([^'"]+)['"]""")),
        ("import", _RX(r"""^\s*export\b[^'"]*\bfrom\s+['"]([^'"]+)['"]""")),
        ("import", _RX(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)""")),
    ),
    "go": (
        ("function", _RX(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")),
        ("class", _RX(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)")),
        ("import", _RX(r"""^\s*(?:import\s+)?(?:\w+\s+)?"([^"]+)"\s*$""")),
    ),
    "rust": (
        ("function", _RX(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)")),
        ("class", _RX(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)")),
        ("import", _RX(r"^\s*use\s+([\w:]+)")),
    ),
    "java": (
        ("class", _RX(r"^\s*(?:(?:public|private|protected|abstract|final|static)\s+)*(?:class|interface|enum|record)\s+([A-Za-z_]\w*)")),
        ("import", _RX(r"^\s*import\s+(?:static\s+)?([\w.]+)")),
    ),
    "csharp": (
        ("class", _RX(r"^\s*(?:(?:public|private|protected|internal|abstract|sealed|static|partial)\s+)*(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)")),
        ("import", _RX(r"^\s*using\s+([\w.]+)\s*;")),
    ),
    "c": (
        ("import", _RX(r"""^\s*#\s*include\s*[<"]([^>"]+)[>"]""")),
        ("class", _RX(r"^\s*(?:typedef\s+)?struct\s+([A-Za-z_]\w*)\s*\{")),
    ),
    "ruby": (
        ("class", _RX(r"^\s*(?:class|module)\s+([A-Z]\w*)")),
        ("function", _RX(r"^\s*def\s+(?:self\.)?([A-Za-z_]\w*[?!]?)")),
        ("import", _RX(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)['"]""")),
    ),
    "php": (
        ("class", _RX(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait)\s+([A-Za-z_]\w*)")),
        ("function", _RX(r"^\s*(?:(?:public|private|protected|static)\s+)*function\s+([A-Za-z_]\w*)")),
    ),
    "mql": (
        ("import", _RX(r"""^\s*#\s*include\s*[<"]([^>"]+)[>"]""")),
        ("class", _RX(r"^\s*class\s+([A-Za-z_]\w*)")),
    ),
}
_ALIASES = {"typescript": "javascript", "kotlin": "java", "cpp": "c", "scala": "java"}


class LightweightFallback:
    name = "lightweight"

    def supports(self, language: str) -> bool:
        return _ALIASES.get(language, language) in _PATTERNS

    def extract(self, path: str, source: str, language: str) -> ExtractionResult:
        patterns = _PATTERNS.get(_ALIASES.get(language, language), ())
        symbols = [
            Symbol(match.group(1), kind, path, number, language, match.start(1))
            for number, line in enumerate(source.splitlines(), start=1)
            for kind, pattern in patterns
            for match in [pattern.search(line)] if match
        ]
        return ExtractionResult(path, tuple(symbols), self.name)


class SymbolExtractor:
    """``extract(..., depth=FAST)`` runs the fast backends; ``depth=DEEP`` (the default) the
    full chain. A fast result is already final (``depth == DEEP``) for languages no deep
    backend handles better than the fast one."""

    def __init__(self, backends: Iterable | None = None, fast_backends: Iterable | None = None) -> None:
        self.backends = tuple(backends) if backends is not None else (
            PythonASTFallback(), TreeSitterExtractor(), LightweightFallback(),
        )
        self.fast_backends = tuple(fast_backends) if fast_backends is not None else (
            PythonOutlineScanner(), LightweightFallback(),
        )
        self._has_deeper: dict[str, bool] = {}

    def supports(self, language: str) -> bool:
        return any(b.supports(language) for b in self.backends + self.fast_backends)

    def has_deeper(self, language: str) -> bool:
        if language not in self._has_deeper:
            self._has_deeper[language] = any(
                b.supports(language) for b in self.backends if not isinstance(b, LightweightFallback)
            )
        return self._has_deeper[language]

    def extract(self, path: str, source: str, language: str, depth: str = DEEP) -> ExtractionResult:
        if depth == FAST:
            result = self._run(self.fast_backends, path, source, language)
            final = FAST if self.has_deeper(language) else DEEP
            return ExtractionResult(result.path, result.symbols, result.backend, result.error, final)
        return self._run(self.backends, path, source, language)

    @staticmethod
    def _run(backends, path: str, source: str, language: str) -> ExtractionResult:
        errors: list[str] = []
        for backend in backends:
            if not backend.supports(language):
                continue
            try:
                result = backend.extract(path, source, language)
            except Exception as exc:  # SyntaxError, RecursionError, a broken optional grammar…
                logger.debug("%s could not extract %s", backend.name, path, exc_info=True)
                errors.append(f"{backend.name}: {type(exc).__name__}: {exc}")
                continue
            if errors:
                return ExtractionResult(path, result.symbols, result.backend, "; ".join(errors), result.depth)
            return result
        return ExtractionResult(path, (), "none", "; ".join(errors) or f"unsupported language: {language}")
