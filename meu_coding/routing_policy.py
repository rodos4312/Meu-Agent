"""Coding workloads on top of the existing "Models by workload" system.

No parallel router: the four coding workloads are names for the existing workload slots
(``agent.workload_routes.SLOTS``) and resolve through ``explicit_routes`` like every other
workload. Without a configured slot the profile's main model is the fallback. The
complexity classifier only picks the coder workload; it never changes what needs approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from meu_coding.coding_interfaces import ImpactReport, ImplementationPlan, RiskLevel
from meu_coding.scope import is_config_path, is_security_path

# coding workload → existing Models-by-workload slot
CODING_WORKLOADS: dict[str, str] = {
    "coding.architect": "complex",
    "coding.simple": "routine",
    "coding.complex": "complex",
    "coding.review": "complex",
    "coding.planner": "complex",
}
# coding.semantic is not a chat slot: it is the embedding provider of coding_engine.semantic
# (meu_coding.embeddings), shown next to the chat routes for one complete picture.

LARGE_CONTEXT_CHARS = 48_000
SIMPLE_FAILURES_BEFORE_ESCALATION = 2
STRONG_MILESTONE_KINDS = frozenset({"analysis", "architecture", "design", "migration", "security"})

SIMPLE_MAX_FILES = 1
COMPLEX_MIN_FILES = 3
COMPLEX_REVERSE_DEPS = 8
HIGH_RISK_REVERSE_DEPS = 25


class Complexity(str, Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"
    HIGH_RISK = "high_risk"


@dataclass(frozen=True)
class Classification:
    complexity: Complexity
    reasons: tuple[str, ...]

    @property
    def workload(self) -> str:
        return "coding.simple" if self.complexity == Complexity.SIMPLE else "coding.complex"


def classify(plan: ImplementationPlan, impact: ImpactReport | None = None) -> Classification:
    """Deterministic: the same plan and impact always give the same class."""
    impact = impact or plan.impact
    targets = (*plan.files_to_change, *plan.new_files)
    reverse = len(impact.reverse_dependencies) if impact else 0
    high = [f"security-sensitive file {p}" for p in targets if is_security_path(p)]
    high += [f"configuration file {p}" for p in targets if is_config_path(p)]
    if plan.risk == RiskLevel.HIGH:
        high.append("the plan is high risk")
    if reverse >= HIGH_RISK_REVERSE_DEPS:
        high.append(f"{reverse} files depend on the change")
    if high:
        return Classification(Complexity.HIGH_RISK, tuple(high))
    complex_ = []
    if len(targets) >= COMPLEX_MIN_FILES:
        complex_.append(f"{len(targets)} files change")
    if reverse >= COMPLEX_REVERSE_DEPS:
        complex_.append(f"{reverse} files depend on the change")
    if impact and any("public API" in r.reason for r in impact.reasons):
        complex_.append("a public API changes")
    if plan.risk == RiskLevel.MEDIUM:
        complex_.append("the plan is medium risk")
    if len(plan.steps) > 6:
        complex_.append(f"{len(plan.steps)} implementation steps")
    if complex_:
        return Classification(Complexity.COMPLEX, tuple(complex_))
    if len(targets) > SIMPLE_MAX_FILES + 1:  # one code file plus its test stays simple
        return Classification(Complexity.COMPLEX, (f"{len(targets)} files change",))
    return Classification(Complexity.SIMPLE, ("small, low-risk change",))


@dataclass(frozen=True)
class RoleRoute:
    workload: str
    provider: str
    model: str
    source: str  # "models_by_workload:<slot>" | "main_model_fallback"

    @property
    def route(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def display(self) -> str:
        return f"{self.provider.replace('-', ' ').title()} · {self.model}"


def _main_route(config: Mapping[str, Any]) -> tuple[str, str] | None:
    main = config.get("model")
    if not isinstance(main, dict):
        return None
    provider, model = str(main.get("provider") or "").strip(), str(main.get("default") or "").strip()
    return (provider, model) if provider and model else None


def _slot_routes(config: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    policy = config.get("smart_model_routing")
    if not isinstance(policy, dict) or not policy.get("routes"):
        return {}
    from agent.workload_routes import explicit_routes

    return explicit_routes(dict(policy))


@dataclass(frozen=True)
class RoutingSignals:
    classification: Classification
    context_chars: int = 0
    files: int = 0
    repair_attempt: int = 0
    simple_failures: int = 0
    milestone_kind: str = ""


@dataclass(frozen=True)
class RouteDecision:
    workload: str
    reasons: tuple[str, ...]
    escalated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"workload": self.workload, "reasons": list(self.reasons), "escalated": self.escalated}


def decide_coder_workload(signals: RoutingSignals) -> RouteDecision:
    """Deterministic. Risk and correctness first: anything that makes a weak model risky starts
    (or continues) on the strong coding.complex route. Cost never overrides this."""
    c = signals.classification
    if c.complexity == Complexity.HIGH_RISK:
        return RouteDecision("coding.complex", ("high risk: strong model from the start", *c.reasons))
    strong = []
    if c.complexity == Complexity.COMPLEX:
        strong += list(c.reasons)
    if signals.context_chars > LARGE_CONTEXT_CHARS:
        strong.append(f"large context ({signals.context_chars:,} chars)")
    if signals.repair_attempt:
        strong.append(f"repair attempt {signals.repair_attempt}")
    if signals.milestone_kind in STRONG_MILESTONE_KINDS:
        strong.append(f"{signals.milestone_kind} milestone")
    if strong:
        return RouteDecision("coding.complex", tuple(strong))
    if signals.simple_failures >= SIMPLE_FAILURES_BEFORE_ESCALATION:
        return RouteDecision("coding.complex",
                             (f"the simple route failed {signals.simple_failures} times — escalated",), escalated=True)
    return RouteDecision("coding.simple", c.reasons)


def review_workload(signals: RoutingSignals | None = None) -> RouteDecision:
    """The Reviewer is never downgraded: always the strong coding.review route."""
    reasons = ("independent strong reviewer",)
    if signals is not None and signals.classification.complexity == Complexity.HIGH_RISK:
        reasons += ("high-risk change: strong review required",)
    return RouteDecision("coding.review", reasons)


def resolve_workloads(config: Mapping[str, Any]) -> dict[str, RoleRoute]:
    """Every coding workload's route from existing settings, with its source."""
    slots = _slot_routes(config)
    main = _main_route(config)
    routes: dict[str, RoleRoute] = {}
    for workload, slot in CODING_WORKLOADS.items():
        chosen = slots.get(slot) or (slots.get("complex") if slot == "routine" else None)
        if chosen:
            used = slot if slots.get(slot) else "complex"
            routes[workload] = RoleRoute(workload, chosen["provider"], chosen["model"], f"models_by_workload:{used}")
        elif main:
            routes[workload] = RoleRoute(workload, main[0], main[1], "main_model_fallback")
    return routes
