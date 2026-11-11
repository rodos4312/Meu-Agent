"""Coding workloads ride the existing Models-by-workload slots; the classifier picks the coder."""

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
from meu_coding.provider_adapter import ProviderCodingModel, ProviderSession, Route, resolve_coding_routes
from meu_coding.routing_policy import CODING_WORKLOADS, Complexity, classify, resolve_workloads

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
