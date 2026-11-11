from meu_coding.context_builder import ContextBuilder, ContextLimits
from meu_coding.interfaces import RepositoryAnalysis
from meu_coding.relevance import RelevanceEngine
from tests.meu_coding.conftest import build_graph

_FILLER = "".join(f"def filler_{i}():\n    return {i}\n\n" for i in range(200))

REPO = {
    "meu/__init__.py": "",
    "meu/sync_manager.py": (
        "import os\n\n" + _FILLER
        + "# keeps phones paired\n@decorated\nclass SyncManager:\n    def pair(self):\n"
        + "        return os.sep\n\n" + _FILLER.replace("filler_", "tail_")
    ),
    "meu/pairing_service.py": "from meu.sync_manager import SyncManager\n\ndef start():\n    return SyncManager()\n",
    "tests/test_sync_manager.py": "from meu.sync_manager import SyncManager\n\ndef test_pair():\n    assert SyncManager().pair()\n",
}


def _build(make_repo, query, budget, limits=None):
    root = make_repo(REPO)
    graph = build_graph(root)
    analysis = RepositoryAnalysis.build(str(root), tuple(graph.files.values()), graph.extractions)
    ranked = RelevanceEngine(analysis, graph).rank(query)
    return ranked, ContextBuilder(analysis, graph, limits).build(query, ranked, budget)


def test_highest_relevance_is_selected_first(make_repo):
    ranked, bundle = _build(make_repo, "SyncManager pairing is broken", 20_000)
    assert bundle.items[0].path == ranked[0].path == "meu/sync_manager.py"
    assert [i.path for i in bundle.items] == [r.path for r in ranked][: len(bundle.items)]


def test_relevant_symbol_gets_its_definition_and_surrounding_context(make_repo):
    _, bundle = _build(make_repo, "SyncManager pairing is broken", 20_000)
    first = bundle.items[0]
    assert first.symbols == ("SyncManager",)
    assert "# keeps phones paired" in first.excerpt and "@decorated" in first.excerpt
    assert "def pair(self):" in first.excerpt and "return os.sep" in first.excerpt
    assert first.reasons and "defines symbol SyncManager" in first.excerpt


def test_no_whole_file_dump(make_repo):
    _, bundle = _build(make_repo, "SyncManager pairing is broken", 200_000)
    source_size = len(REPO["meu/sync_manager.py"])
    first = bundle.items[0]
    assert first.size < source_size / 10
    assert "filler_150" not in first.excerpt and "tail_10" not in first.excerpt


def test_budget_is_respected_and_overflow_is_reported(make_repo):
    for budget in (150, 400, 1_000, 5_000):
        _, bundle = _build(make_repo, "SyncManager pairing is broken", budget)
        assert len(bundle.render()) <= budget
        assert bundle.size <= budget
    _, tiny = _build(make_repo, "SyncManager pairing is broken", 150)
    assert tiny.omitted


def test_unmentioned_files_contribute_an_outline(make_repo):
    _, bundle = _build(make_repo, "SyncManager pairing is broken", 20_000)
    service = next(i for i in bundle.items if i.path == "meu/pairing_service.py")
    assert "from meu.sync_manager import SyncManager" in service.excerpt
    assert "def start():" in service.excerpt
    assert "return SyncManager()" not in service.excerpt


def test_items_report_size_lines_and_dependencies(make_repo):
    _, bundle = _build(make_repo, "SyncManager pairing is broken", 20_000)
    first = bundle.items[0]
    assert first.size == len(first.excerpt)
    assert 1 <= first.start_line <= first.end_line
    assert "imported by: meu/pairing_service.py" in first.excerpt


def test_symbol_excerpt_is_capped(make_repo):
    limits = ContextLimits(max_symbol_lines=2, leading_lines=0)
    _, bundle = _build(make_repo, "SyncManager", 20_000, limits)
    first = bundle.items[0]
    assert first.end_line - first.start_line + 1 == 2


def test_output_is_deterministic(make_repo):
    _, a = _build(make_repo, "SyncManager pairing is broken", 3_000)
    _, b = _build(make_repo, "SyncManager pairing is broken", 3_000)
    assert a == b and a.render() == b.render()
