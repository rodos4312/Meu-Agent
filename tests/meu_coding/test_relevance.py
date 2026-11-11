from meu_coding.interfaces import RepositoryAnalysis
from meu_coding.relevance import RelevanceEngine, parse_query
from tests.meu_coding.conftest import build_graph

REPO = {
    "meu/__init__.py": "",
    "meu/sync_manager.py": "class SyncManager:\n    def pair(self):\n        return 1\n",
    "meu/pairing_service.py": "from meu.sync_manager import SyncManager\n\ndef start():\n    return SyncManager()\n",
    "meu/pairing_ui.py": "from meu.pairing_service import start\n\ndef show():\n    return start()\n",
    "meu/pairing_pairing_sync_tools.py": "def pairing_sync_pairing():\n    return 'pairing sync'\n",
    "meu/unrelated.py": "def noise():\n    return 0\n",
    "tests/test_sync_manager.py": "from meu.sync_manager import SyncManager\n\ndef test_pair():\n    assert SyncManager().pair()\n",
}


def _engine(make_repo, files=REPO):
    graph = build_graph(make_repo(files))
    analysis = RepositoryAnalysis.build(str(graph), tuple(graph.files.values()), graph.extractions)
    return RelevanceEngine(analysis, graph)


def _rank(engine, query, **kw):
    return {item.path: item for item in engine.rank(query, limit=None, **kw)}


def test_explicit_file_mention_dominates_keyword_matches(make_repo):
    ranked = _rank(_engine(make_repo), "pairing sync pairing problem in unrelated.py")
    assert next(iter(ranked)) == "meu/unrelated.py"
    assert "explicitly mentioned" in ranked["meu/unrelated.py"].reasons
    assert ranked["meu/unrelated.py"].score > ranked["meu/pairing_pairing_sync_tools.py"].score


def test_explicit_symbol_strongly_boosts_the_defining_file(make_repo):
    ranked = _rank(_engine(make_repo), "why does SyncManager drop the pairing?")
    top = next(iter(ranked.values()))
    assert top.path == "meu/sync_manager.py"
    assert "defines symbol SyncManager" in top.reasons
    assert top.symbols == ("SyncManager",)
    assert top.score >= ranked["meu/pairing_pairing_sync_tools.py"].score + 30


def test_direct_dependency_ranks_above_unrelated_file(make_repo):
    ranked = _rank(_engine(make_repo), "change SyncManager")
    service = ranked["meu/pairing_service.py"]
    assert "imports meu/sync_manager.py" in service.reasons
    assert "meu/unrelated.py" not in ranked
    ui = ranked["meu/pairing_ui.py"]
    assert "two imports from meu/sync_manager.py" in ui.reasons
    assert service.score > ui.score


def test_related_test_is_found_and_reported(make_repo):
    ranked = _rank(_engine(make_repo), "SyncManager.pair is wrong")
    assert "tests meu/sync_manager.py" in ranked["tests/test_sync_manager.py"].reasons
    assert any(r.startswith("related test exists") for r in ranked["meu/sync_manager.py"].reasons)


def test_dependencies_of_an_explicit_file_are_boosted(make_repo):
    ranked = _rank(_engine(make_repo), "look at meu/pairing_service.py")
    assert "imported by meu/pairing_service.py" in ranked["meu/sync_manager.py"].reasons


def test_recently_changed_boost(make_repo):
    engine = _engine(make_repo)
    plain = _rank(engine, "SyncManager")["meu/pairing_service.py"].score
    boosted = _rank(engine, "SyncManager", recently_changed=["meu/pairing_service.py"])
    assert boosted["meu/pairing_service.py"].score == plain + 8
    assert "recently changed" in boosted["meu/pairing_service.py"].reasons


def test_every_result_has_a_score_and_reasons(make_repo):
    for item in _engine(make_repo).rank("pairing SyncManager", limit=None):
        assert item.score > 0 and item.reasons


def test_results_are_deterministic(make_repo):
    engine = _engine(make_repo)
    first = engine.rank("pairing sync manager", limit=None)
    assert first == engine.rank("pairing sync manager", limit=None)
    assert [i.score for i in first] == sorted((i.score for i in first), reverse=True)


def test_plain_english_words_are_not_strong_symbols():
    parsed = parse_query("please start the `run` job in SyncManager and sync_manager.py")
    assert {"SyncManager", "run", "sync_manager"} <= parsed.strong_identifiers
    assert "start" in parsed.weak_identifiers and "start" not in parsed.strong_identifiers
    assert "sync_manager.py" in parsed.paths


class _Exhaustive(RelevanceEngine):
    """Scores every file: the reference the candidate index must reproduce exactly."""

    def _candidates(self, parsed):
        return sorted(self._paths)


def test_candidate_index_ranks_exactly_like_scoring_every_file(make_repo):
    graph = build_graph(make_repo(REPO))
    analysis = RepositoryAnalysis.build("repo", tuple(graph.files.values()), graph.extractions)
    indexed, exhaustive = RelevanceEngine(analysis, graph), _Exhaustive(analysis, graph)
    for query in ("SyncManager pairing", "unrelated.py noise", "pairing ui show", "sync", "tests", "x"):
        assert indexed.rank(query, limit=None) == exhaustive.rank(query, limit=None), query
