"""Coding workloads ride the existing Models-by-workload slots; the classifier picks the coder with
recorded reasons, escalation is controlled, risky work starts strong, and the Reviewer is never
downgraded."""

from dataclasses import replace

from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    CodingRequest,
    CodingTask,
    EditStrategy,
    ImpactReport,
    ImplementationPlan,
    RepairRequest,
    ReviewResult,
    ReviewStatus,
    RiskLevel,
    RiskReason,
    StrategyChoice,
    TestPlan,
)
from meu_coding.embeddings import resolve_embedding_provider
from meu_coding.provider_adapter import (
    CodingRoutes,
    ProviderCodingModel,
    ProviderError,
    ProviderSession,
    Route,
    resolve_coding_routes,
)
from meu_coding.routing_policy import (
    CODING_WORKLOADS,
    LARGE_CONTEXT_CHARS,
    Classification,
    Complexity,
    RoutingSignals,
    classify,
    decide_coder_workload,
    resolve_workloads,
)

WORKLOAD_CONFIG = {
    "model": {"provider": "deepseek", "default": "deepseek-main"},
    "smart_model_routing": {"enabled": True, "provider": "deepseek", "routes": {
        "routine": {"provider": "deepseek", "model": "deepseek-flash-x"},
        "complex": {"provider": "deepseek", "model": "deepseek-pro-x"}}},
}


def _impact(reverse=0, reasons=()):
    return ImpactReport((), (), (), tuple(f"r{i}.py" for i in range(reverse)), (), (), (), RiskLevel.LOW,
                        tuple(RiskReason(RiskLevel.MEDIUM, r) for r in reasons))


def _plan(files=("calc/ops.py", "tests/test_ops.py"), risk=RiskLevel.LOW, impact=None, steps=("a",)):
    return ImplementationPlan("s", tuple(files), (), (), tuple(steps), TestPlan(), risk, impact or _impact())


def test_simple_complex_and_high_risk_classes():
    assert classify(_plan()).complexity == Complexity.SIMPLE
    assert classify(_plan(files=("a.py", "b.py", "c.py"))).complexity == Complexity.COMPLEX
    assert classify(_plan(impact=_impact(reverse=9))).complexity == Complexity.COMPLEX
    assert classify(_plan(impact=_impact(reasons=("public API changed: f is used",)))).complexity == Complexity.COMPLEX
    high = classify(_plan(files=("app/auth/tokens.py",)))
    assert high.complexity == Complexity.HIGH_RISK and "security" in high.reasons[0]
    assert classify(_plan(files=("pyproject.toml",))).complexity == Complexity.HIGH_RISK
    assert classify(_plan(risk=RiskLevel.HIGH)).complexity == Complexity.HIGH_RISK
    assert classify(_plan(impact=_impact(reverse=30))).complexity == Complexity.HIGH_RISK


def test_workloads_map_onto_existing_slots_and_fall_back_to_the_main_model():
    assert set(CODING_WORKLOADS.values()) <= {"routine", "complex"}  # existing slots only
    routes = resolve_workloads(WORKLOAD_CONFIG)
    assert routes["coding.architect"].model == routes["coding.review"].model == "deepseek-pro-x"
    assert routes["coding.simple"].model == "deepseek-flash-x"
    assert routes["coding.simple"].source == "models_by_workload:routine"
    assert routes["coding.simple"].display == "Deepseek · deepseek-flash-x"
    fallback = resolve_workloads({"model": WORKLOAD_CONFIG["model"]})
    assert {r.source for r in fallback.values()} == {"main_model_fallback"}
    only_complex = dict(WORKLOAD_CONFIG, smart_model_routing={"routes": {
        "complex": {"provider": "deepseek", "model": "deepseek-pro-x"}}})
    assert resolve_workloads(only_complex)["coding.simple"].source == "models_by_workload:complex"
    assert resolve_workloads({}) == {}


class _NoCalls:
    def complete(self, route, messages, timeout):
        raise AssertionError("no model call expected")


def _request(plan, repair=None):
    choice = StrategyChoice(EditStrategy.SEARCH_REPLACE, "p", "r")
    return CodingRequest(CodingTask("t"), plan, None, choice, 1000, repair)


def test_coder_uses_simple_route_only_for_simple_first_attempts_and_records_why():
    routes = resolve_coding_routes(WORKLOAD_CONFIG).routes
    coder = ProviderCodingModel(ProviderSession(_NoCalls(), routes))
    assert coder.route_for(_request(_plan())) == Route("deepseek", "deepseek-flash-x")
    assert coder.last_routing["workload"] == "coding.simple" and coder.last_routing["complexity"] == "simple"
    assert coder.route_for(_request(_plan(files=("a.py", "b.py", "c.py")))) == Route("deepseek", "deepseek-pro-x")
    assert coder.last_routing["workload"] == "coding.complex"
    assert coder.route_for(_request(_plan(files=("app/auth/x.py",)))) == Route("deepseek", "deepseek-pro-x")
    assert coder.last_routing["complexity"] == "high_risk" and coder.last_routing["reasons"]
    review = ReviewResult(ReviewStatus.FIX, (), ("fix",), 0.9, "r")
    previous = CodeChangeProposal((), StrategyChoice(EditStrategy.SEARCH_REPLACE, "p", "r"))
    repair = RepairRequest(1, previous, review)
    assert coder.route_for(_request(_plan(), repair)) == Route("deepseek", "deepseek-pro-x")  # repairs go strong


def test_architect_and_reviewer_are_strong_and_independent_routes():
    resolution = resolve_coding_routes(WORKLOAD_CONFIG)
    routes = resolution.routes
    assert routes.architect == routes.reviewer == Route("deepseek", "deepseek-pro-x")
    assert routes.sources["reviewer"] == "models_by_workload:complex"
    assert resolution.source == "models_by_workload"
    fallback = resolve_coding_routes({"model": WORKLOAD_CONFIG["model"]})
    assert fallback.source == "main_model_fallback" and fallback.routes.architect == Route("deepseek", "deepseek-main")
    assert replace(routes) == routes


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


def test_escalation_after_two_simple_failures():
    assert decide_coder_workload(RoutingSignals(SIMPLE, simple_failures=1)).workload == "coding.simple"
    escalated = decide_coder_workload(RoutingSignals(SIMPLE, simple_failures=2))
    assert escalated.workload == "coding.complex" and escalated.escalated
    assert "failed 2 times" in escalated.reasons[0]


def test_reviewer_is_never_routed_to_the_routine_model():
    routes = resolve_workloads(WORKLOAD_CONFIG)
    assert routes["coding.review"].source == "models_by_workload:complex"
    assert routes["coding.review"].model == routes["coding.complex"].model != routes["coding.simple"].model


def test_planner_route_uses_the_existing_workload_slots():
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

    context = prepare_context(analyze_repository(make_git_repo(tmp_path)), TASK, 4_000)
    routes = CodingRoutes(Route("strong", "s"), Route("strong", "s"), Route("strong", "s"), Route("cheap", "c"))
    client = _Client({"cheap:c"})
    model = ProviderCodingModel(ProviderSession(client, routes, max_format_retries=0))
    request = CodingRequest(TASK, _plan(), context, StrategyChoice(EditStrategy.SEARCH_REPLACE, "p", "r"), 4_000)
    model.propose(request)
    assert client.calls == ["cheap:c", "cheap:c", "strong:s"]
    assert model.last_routing["workload"] == "coding.complex" and model.last_routing["escalated"]
    assert "failed 2 times" in model.last_routing["reasons"][0]
