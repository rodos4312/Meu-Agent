from meu_coding.symbols import (
    LightweightFallback,
    PythonASTFallback,
    SymbolExtractor,
    TreeSitterExtractor,
)

PY = '''\
import os
from .sibling import helper as h
from pkg.sub import Thing

LIMIT = 3


class SyncManager(Base):
    def start(self):
        return h(os.getcwd(), self.local)

    async def stop(self):
        pass


def make_manager():
    return SyncManager()
'''


def _by(result, kind):
    return {s.name: s for s in result.symbols if s.kind == kind}


def test_python_class_function_and_method():
    result = SymbolExtractor().extract("pkg/sync.py", PY, "python")
    assert result.backend == "python-ast" and result.error is None
    cls = _by(result, "class")["SyncManager"]
    assert (cls.line, cls.column, cls.end_line, cls.container) == (8, 0, 13, None)
    func = _by(result, "function")["make_manager"]
    assert (func.line, func.language, func.path) == (16, "python", "pkg/sync.py")
    methods = _by(result, "method")
    assert set(methods) == {"start", "stop"}
    assert methods["start"].container == "SyncManager"
    assert methods["start"].qualified_name == "SyncManager.start"
    assert _by(result, "variable")["LIMIT"].line == 5


def test_python_imports_keep_module_relative_level_and_imported_name():
    imports = [(s.name, s.container) for s in SymbolExtractor().extract("a.py", PY, "python").imports]
    assert imports == [("os", None), (".sibling", "helper"), ("pkg.sub", "Thing")]


def test_python_references_are_recorded_once_per_container():
    refs = SymbolExtractor().extract("a.py", PY, "python").references
    pairs = {(s.name, s.container) for s in refs}
    assert ("helper", "SyncManager.start") in pairs  # via the alias ``h``
    assert ("getcwd", "SyncManager.start") in pairs
    assert ("SyncManager", "make_manager") in pairs
    assert len(pairs) == len(refs)


def test_noisy_low_value_references_are_not_stored():
    names = {s.name for s in SymbolExtractor().extract("a.py", PY, "python").references}
    assert not names & {"self", "local", "Base", "h"}
    everything = PythonASTFallback(keep_low_references=True).extract("a.py", PY, "python")
    assert {"self", "local", "Base"} <= {s.name for s in everything.references}


def test_parser_unavailable_falls_back_without_failing():
    extractor = SymbolExtractor()
    tree_sitter = next(b for b in extractor.backends if isinstance(b, TreeSitterExtractor))
    tree_sitter._factory = None
    result = extractor.extract("web/app.ts", "export class Store {}\nimport x from './x'\n", "typescript")
    assert result.backend == "lightweight"
    assert {(s.kind, s.name) for s in result.symbols} == {("class", "Store"), ("import", "./x")}


def test_grammar_lookup_failure_is_unsupported_not_fatal():
    def factory(language):
        raise LookupError(language)
    assert TreeSitterExtractor(factory).supports("python") is False


def test_unsupported_language_returns_empty_result():
    result = SymbolExtractor().extract("notes.xyz", "anything", "unknown")
    assert result.symbols == () and result.backend == "none"
    assert "unsupported language" in result.error


def test_malformed_python_degrades_to_regex_and_reports_the_error():
    broken = "class Ok:\n    pass\n\ndef broken(:\n    return\n"
    result = SymbolExtractor([PythonASTFallback(), LightweightFallback()]).extract("b.py", broken, "python")
    assert result.backend == "lightweight"
    assert "SyntaxError" in result.error
    assert {s.name for s in result.definitions} == {"Ok", "broken"}


def test_every_backend_failing_does_not_crash():
    class Exploding:
        name = "boom"

        def supports(self, language):
            return True

        def extract(self, path, source, language):
            raise RuntimeError("grammar crashed")

    result = SymbolExtractor([Exploding()]).extract("x.py", "x", "python")
    assert result.symbols == () and "grammar crashed" in result.error


def test_binary_like_garbage_source_does_not_crash():
    result = SymbolExtractor().extract("g.py", "\x00\x01� def (((", "python")
    assert result.error


class _Node:
    def __init__(self, type_, start, end, children=(), name=None, row=0):
        self.type, self.start_byte, self.end_byte = type_, start, end
        self.children, self._name = list(children), name
        self.start_point, self.end_point = (row, 0), (row, 0)

    def child_by_field_name(self, field):
        return self._name if field == "name" else None


def test_tree_sitter_walk_extracts_named_definitions_and_imports():
    source = 'import "fmt"\nclass Box { open() {} }'
    data = source.encode()
    method_name = _Node("property_identifier", data.index(b"open"), data.index(b"open") + 4)
    method = _Node("method_definition", 0, 0, name=method_name, row=1)
    class_name = _Node("identifier", data.index(b"Box"), data.index(b"Box") + 3)
    klass = _Node("class_declaration", 0, 0, children=[method], name=class_name, row=1)
    imp = _Node("import_statement", 0, len("import \"fmt\""))
    root = _Node("program", 0, len(data), children=[imp, klass])

    class Parser:
        def parse(self, _data):
            return type("Tree", (), {"root_node": root})()

    result = TreeSitterExtractor(lambda language: Parser()).extract("a.js", source, "javascript")
    got = [(s.kind, s.name, s.container, s.line) for s in result.symbols]
    assert got == [("import", "fmt", None, 1), ("class", "Box", None, 2), ("method", "open", "Box", 2)]
