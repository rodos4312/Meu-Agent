"""Phase 7 routing on top of Models by workload: deterministic decisions with recorded reasons,
controlled escalation, strong routes for risky work, and a Reviewer that is never downgraded."""

from meu_coding.embeddings import resolve_embedding_provider
from meu_coding.provider_adapter import CodingRoutes, ProviderCodingModel, ProviderError, ProviderSession, Route
from meu_coding.routing_policy import (
    LARGE_CONTEXT_CHARS,
    Classification,
    Complexity,
    RoutingSignals,
    decide_coder_workload,
    resolve_workloads,
    review_workload,
)

SIMPLE = Classification(Complexity.SIMPLE, ("small, low-risk change",))
COMPLEX = Classification(Complexity.COMPLEX, ("3 files change",))
HIGH = Classification(Complexity.HIGH_RISK, ("security-sensitive file auth/x.py",))


def test_simple_route_for_small_low_risk_first_attempts():
    decision = decide_coder_workload(RoutingSignals(SIMPLE, context_chars=2_000, files=1))
    assert decision.workload == "coding.simple" and not decision.escalated


def test_complex_route_with_reasons():
    decision = decide_coder_workload(RoutingSignals(COMPLEX))
    assert decision.workload == "coding.complex" and "3 files change" in decision.reasons


def test_large_context_repairs_and_hard_milestones_start_strong():
    assert decide_coder_workload(RoutingSignals(SIMPLE, context_chars=LARGE_CONTEXT_CHARS + 1)).workload == \
        "coding.complex"
    assert "repair attempt 1" in decide_coder_workload(RoutingSignals(SIMPLE, repair_attempt=1)).reasons
    assert "analysis milestone" in decide_coder_workload(RoutingSignals(SIMPLE, milestone_kind="analysis")).reasons


def test_high_risk_requires_the_strong_model_and_strong_review():
    decision = decide_coder_workload(RoutingSignals(HIGH, context_chars=10))
    assert decision.workload == "coding.complex" and decision.reasons[0].startswith("high risk")
    review = review_workload(RoutingSignals(HIGH))
    assert review.workload == "coding.review" and "high-risk change: strong review required" in review.reasons
    assert review_workload(RoutingSignals(SIMPLE)).workload == "coding.review"  # never a cheaper reviewer


def test_escalation_after_two_simple_failures():
    assert decide_coder_workload(RoutingSignals(SIMPLE, simple_failures=1)).workload == "coding.simple"
    escalated = decide_coder_workload(RoutingSignals(SIMPLE, simple_failures=2))
    assert escalated.workload == "coding.complex" and escalated.escalated
    assert "failed 2 times" in escalated.reasons[0]


def test_planner_route_uses_the_existing_workload_slots():
    from tests.meu_coding.test_routing_policy import WORKLOAD_CONFIG

    routes = resolve_workloads(WORKLOAD_CONFIG)
    assert routes["coding.planner"].source == "models_by_workload:complex"
    assert routes["coding.planner"].model == routes["coding.architect"].model
    fallback = resolve_workloads({"model": WORKLOAD_CONFIG["model"]})
    assert fallback["coding.planner"].source == "main_model_fallback"


def test_semantic_route_is_the_embedding_provider_setting():
    assert resolve_embedding_provider({}).status == "off"
    local = resolve_embedding_provider({"coding_engine": {"semantic": {"provider": "local"}}})
    assert local.status == "enabled" and local.provider.identity.kind == "local-lexical"
    missing = resolve_embedding_provider({"coding_engine": {"semantic": {"provider": "openai"}}})
    assert missing.status == "unavailable" and "model" in missing.reason
    no_key = resolve_embedding_provider({"coding_engine": {"semantic": {"provider": "openai", "model": "e-1"}}},
                                        has_credentials=lambda name: False)
    assert no_key.status == "unavailable" and "credentials" in no_key.reason
    api = resolve_embedding_provider({"coding_engine": {"semantic": {"provider": "openai", "model": "e-1"}}},
                                     has_credentials=lambda name: True)
    assert api.status == "enabled" and api.reason == "openai · e-1"


class _Client:
    def __init__(self, fail_routes):
        self.fail_routes = set(fail_routes)
        self.calls = []

    def complete(self, route, messages, timeout):
        self.calls.append(str(route))
        if str(route) in self.fail_routes:
            raise ProviderError(f"{route} failed: Timeout")
        return '{"operations": [], "notes": "nothing"}'


def test_coder_escalates_from_the_simple_route_and_records_why(tmp_path):
    from meu_coding.coding_interfaces import CodingRequest, EditStrategy, StrategyChoice
    from meu_coding.intelligence import analyze_repository
    from meu_coding.orchestrator import prepare_context
    from tests.meu_coding.phase3_support import TASK, make_git_repo
    from tests.meu_coding.test_routing_policy import _plan

    context = prepare_context(analyze_repository(make_git_repo(tmp_path)), TASK, 4_000)
    routes = CodingRoutes(Route("strong", "s"), Route("strong", "s"), Route("strong", "s"), Route("cheap", "c"))
    client = _Client({"cheap:c"})
    model = ProviderCodingModel(ProviderSession(client, routes, max_format_retries=0))
    request = CodingRequest(TASK, _plan(), context, StrategyChoice(EditStrategy.SEARCH_REPLACE, "p", "r"), 4_000)
    model.propose(request)
    assert client.calls == ["cheap:c", "cheap:c", "strong:s"]
    assert model.last_routing["workload"] == "coding.complex" and model.last_routing["escalated"]
    assert "failed 2 times" in model.last_routing["reasons"][0]
