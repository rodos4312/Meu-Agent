"""Phase 7 hybrid relevance: semantic similarity and memory are bounded DISCOVERY signals.
Structural evidence outranks them, they never apply to protected or security files, and a file
found only through them can never become an edit target."""

import pytest

from meu_coding.architect import draft_plan, validate_plan
from meu_coding.coding_interfaces import CodingTask
from meu_coding.impact import ImpactAnalyzer
from meu_coding.intelligence import RepositoryIntelligence
from meu_coding.orchestrator import prepare_context
from meu_coding.relevance import WEIGHTS
from meu_coding.semantic_index import SemanticIndex, SemanticLayer
from meu_coding.semantic_search import SemanticHit
from tests.meu_coding.phase7_support import ConceptEmbeddings

FILES = {
    "sync/session.py": "from sync.state import State\n\n\ndef open_session(state):\n    '''open a session'''\n"
                       "    return State(state)\n",
    "sync/state.py": "class State:\n    def __init__(self, value):\n        self.value = value\n",
    "net/redial.py": "def redial_with_backoff(conn):\n    '''retry the link with backoff after it dropped'''\n"
                     "    return conn.retry(backoff=2)\n",
    "auth/tokens.py": "def refresh_tokens(store):\n    '''retry token refresh with backoff, resume the link'''\n"
                      "    return store.retry()\n",
    "tests/test_session.py": "from sync.session import open_session\n\n\ndef test_open():\n"
                             "    assert open_session(1)\n",
}


@pytest.fixture
def intel(make_repo):
    root = make_repo(FILES)
    layer = SemanticLayer(SemanticIndex(str(root), ConceptEmbeddings(), ":memory:"), "enabled", "test")
    intelligence = RepositoryIntelligence(root, semantic=layer)
    intelligence.analyze_repository()
    return intelligence


def _by_path(ranked):
    return {r.path: r for r in ranked}


def test_semantic_finds_a_differently_named_file_with_an_explained_score(intel):
    ranked = _by_path(intel.rank("make the connection resume after it drops"))
    hit = ranked["net/redial.py"]
    components = hit.component_totals()
    assert "semantic_embedding" in components and components["semantic_embedding"] <= WEIGHTS["semantic_max"]
    assert any(r.startswith("semantic similarity") for r in hit.reasons)
    assert intel.last_ranking["semantic_hits"] >= 1


def test_exact_symbol_beats_a_semantic_only_hit(intel):
    ranked = intel.rank("fix open_session so the connection can resume")
    assert ranked[0].path == "sync/session.py"
    assert "symbol_match" in ranked[0].component_totals()
    semantic_only = [r for r in ranked if r.discovery_only]
    assert semantic_only and all(r.score < ranked[0].score for r in semantic_only)


def test_direct_dependency_outranks_a_weak_semantic_match(intel):
    ranked = _by_path(intel.rank("change open_session to resume"))
    dependency = ranked["sync/state.py"]
    assert "dependency_proximity" in dependency.component_totals()
    weak = [r for r in ranked.values() if r.discovery_only]
    assert weak and all(r.score < dependency.score for r in weak)


def test_security_files_get_no_semantic_points(intel):
    ranked = _by_path(intel.rank("resume the link with retry and backoff"))
    assert "auth/tokens.py" not in ranked or "semantic_embedding" not in ranked["auth/tokens.py"].component_totals()


def test_semantic_only_hit_never_enters_the_write_scope(intel):
    task = CodingTask("make the connection resume after it drops")
    context = prepare_context(intel, task, 8_000)
    redial = next(r for r in context.ranked if r.path == "net/redial.py")
    assert redial.discovery_only
    plan = draft_plan(context, ImpactAnalyzer(intel.graph))
    assert "net/redial.py" not in plan.files_to_change
    forced = plan.__class__(**{**plan.__dict__, "files_to_change": ("net/redial.py",),
                               "unresolved_questions": ()})
    errors = validate_plan(forced, context).errors
    assert any("semantic similarity or memory" in e for e in errors)


def test_naming_the_file_makes_it_a_legitimate_target(intel):
    task = CodingTask("make the connection resume after it drops", explicit_files=("net/redial.py",))
    context = prepare_context(intel, task, 8_000)
    plan = draft_plan(context, ImpactAnalyzer(intel.graph))
    assert plan.files_to_change == ("net/redial.py",)


def test_memory_hint_is_discovery_only_and_skips_protected_paths(intel):
    ranked = _by_path(intel.rank("unrelated words", memory_paths=(("sync/state.py", "State is immutable"),
                                                                  (".env", "never"))))
    assert ranked["sync/state.py"].discovery_only and ranked["sync/state.py"].component_totals() == {"memory": 5.0}
    assert ".env" not in ranked


def test_hybrid_ranking_is_deterministic(intel):
    query = "fix open_session so the connection can resume"
    first = [(r.path, r.score, r.components) for r in intel.rank(query)]
    assert all([(r.path, r.score, r.components) for r in intel.rank(query)] == first for _ in range(3))


def test_components_add_up_to_the_score(intel):
    for item in intel.rank("fix open_session so the connection can resume"):
        assert round(sum(item.component_totals().values()), 1) == pytest.approx(item.score, abs=0.2)


def test_semantic_hit_on_unknown_path_is_ignored(intel):
    engine = intel._engine
    ghost = SemanticHit("gone/file.py", "x", "f", "", "function", 1, 2, 0.99)
    assert all(r.path != "gone/file.py" for r in engine.rank("anything", semantic_hits=[ghost]))
