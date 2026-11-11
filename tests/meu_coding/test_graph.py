from meu_coding.interfaces import DependencyEdge, EdgeKind
from tests.meu_coding.conftest import build_graph

CHAIN = {
    "app/__init__.py": "",
    "app/a.py": "from app import b\n\ndef run():\n    return b.Engine().go()\n",
    "app/b.py": "from .c import helper\n\nclass Engine:\n    def go(self):\n        return helper()\n",
    "app/c.py": "import os\n\ndef helper():\n    return os.sep\n",
    "web/main.ts": "import { x } from './util'\nimport React from 'react'\n",
    "web/util.ts": "export const x = () => 1\n",
}


def test_chain_dependencies_and_reverse_dependencies(make_repo):
    graph = build_graph(make_repo(CHAIN))
    assert graph.get_dependencies("app/a.py") == ("app/b.py",)
    assert graph.get_dependencies("app/b.py") == ("app/c.py",)
    assert graph.get_reverse_dependencies("app/b.py") == ("app/a.py",)
    assert graph.get_reverse_dependencies("app/c.py") == ("app/b.py",)
    assert graph.get_reverse_dependencies("app/a.py") == ()


def test_external_modules_are_kept_apart_from_files(make_repo):
    graph = build_graph(make_repo(CHAIN))
    assert graph.get_dependencies("app/c.py") == ()
    assert graph.get_dependencies("app/c.py", include_external=True) == ("module:os",)
    assert graph.get_dependencies("web/main.ts", include_external=True) == ("module:react", "web/util.ts")


def test_targets_accept_module_names_and_windows_paths(make_repo):
    graph = build_graph(make_repo(CHAIN))
    assert graph.get_dependencies("app.a") == ("app/b.py",)
    assert graph.get_reverse_dependencies("app\\c.py") == ("app/b.py",)


def test_symbol_lookup_by_name_and_qualified_name(make_repo):
    graph = build_graph(make_repo(CHAIN))
    (engine,) = graph.lookup_symbol("Engine")
    assert (engine.path, engine.kind, engine.line) == ("app/b.py", "class", 3)
    (go,) = graph.lookup_symbol("Engine.go")
    assert go.kind == "method" and go.container == "Engine"
    assert graph.lookup_symbol("missing") == ()
    assert graph.files_for_symbol("helper") == ("app/c.py",)
    assert [s.name for s in graph.symbols_for_file("app/b.py")] == ["Engine", "go"]


def test_references_resolve_through_imports(make_repo):
    graph = build_graph(make_repo(CHAIN))
    assert graph.referencing_files("helper") == ("app/b.py",)
    assert graph.referencing_files("Engine") == ("app/a.py",)


def test_related_files_by_import_distance(make_repo):
    graph = build_graph(make_repo(CHAIN))
    assert graph.related_files("app/a.py") == {"app/b.py": 1, "app/c.py": 2}
    assert graph.related_files("app/a.py", max_distance=1) == {"app/b.py": 1}


def test_edges_cover_every_relationship_kind(make_repo):
    edges = set(build_graph(make_repo(CHAIN)).edges())
    helper = "symbol:app/c.py:helper:3"
    go = "symbol:app/b.py:Engine.go:4"
    assert DependencyEdge("app/a.py", "app/b.py", EdgeKind.IMPORTS) in edges
    assert DependencyEdge("app/c.py", "module:os", EdgeKind.IMPORTS) in edges
    assert DependencyEdge("app/c.py", helper, EdgeKind.DEFINES) in edges
    assert DependencyEdge(helper, "app/c.py", EdgeKind.BELONGS_TO) in edges
    assert DependencyEdge("app/b.py", helper, EdgeKind.REFERENCES) in edges
    assert DependencyEdge(go, helper, EdgeKind.REFERENCES) in edges


def test_graph_is_deterministic(make_repo):
    root = make_repo(CHAIN)
    assert build_graph(root).edges() == build_graph(root).edges()
