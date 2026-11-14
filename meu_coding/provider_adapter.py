"""Provider adapter: MEU's existing LLM stack behind the Phase 2 model protocols.

Calls go through ``agent.auxiliary_client.call_llm`` with an explicit provider and model,
so credentials, base URLs, key rotation, rate limits and fallbacks are MEU's own; nothing
here reads or stores a secret. Routes come from the user's "models by workload" policy
(``complex`` → Architect, Coder, Reviewer; ``routine`` → Coder for simple changes) or from
an explicit :class:`CodingRoutes`; no model name is hard-coded.

Every response is parsed and validated (``meu_coding.schemas``) before it becomes data.
A malformed response is retried once with the validation errors; a provider error is not
retried here (MEU's client already applies its own retry and fallback policy). Failures are
controlled: the Architect raises ``PlanningError``, the Coder returns no edits, the
Reviewer returns a BLOCK finding. No response can select a command, approve anything or
touch a file.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from meu_coding.architect import PlanningError
from meu_coding.coding_interfaces import (
    CheckSpec,
    CoderOutput,
    CodingRequest,
    FindingCategory,
    ImplementationPlan,
    PlanningRequest,
    ReviewFinding,
    ReviewRequest,
    ReviewStatus,
    TaskContext,
    TestPlan,
    max_risk,
)
from meu_coding.schemas import SchemaError, parse_json_object, validate_architect, validate_coder, validate_reviewer

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0


class ProviderError(Exception):
    """The provider call itself failed (unavailable, timeout, credentials)."""


@dataclass(frozen=True)
class Route:
    provider: str
    model: str

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class CodingRoutes:
    architect: Route
    coder: Route
    reviewer: Route
    coder_simple: Route | None = None
    # role → "models_by_workload:<slot>" | "main_model_fallback" (display/audit only)
    sources: dict[str, str] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class RouteResolution:
    routes: CodingRoutes
    source: str  # "models_by_workload" | "main_model_fallback"


def resolve_coding_routes(config: Mapping[str, Any]) -> RouteResolution:
    """Coding routes from existing settings only (``meu_coding.routing_policy``): each coding
    workload uses its Models-by-workload slot, else the profile's main model."""
    from meu_coding.routing_policy import resolve_workloads

    workloads = resolve_workloads(config)
    needed = ("coding.architect", "coding.complex", "coding.review")
    if any(w not in workloads for w in needed):
        raise ProviderError("No model is configured: choose a main model or Models by workload in Settings.")

    def route(workload: str) -> Route:
        return Route(workloads[workload].provider, workloads[workload].model)

    simple = workloads.get("coding.simple")
    sources = {"architect": workloads["coding.architect"].source, "coder": workloads["coding.complex"].source,
               "reviewer": workloads["coding.review"].source}
    if simple is not None:
        sources["coder_simple"] = simple.source
    routes = CodingRoutes(architect=route("coding.architect"), coder=route("coding.complex"),
                         reviewer=route("coding.review"),
                         coder_simple=Route(simple.provider, simple.model) if simple else None, sources=sources)
    source = "models_by_workload" if any(v.startswith("models_by_workload") for v in sources.values())         else "main_model_fallback"
    return RouteResolution(routes, source)


def provider_has_credentials(provider: str) -> bool:
    """Whether MEU's own resolver finds a key for ``provider`` (the key itself is not returned)."""
    from hermes_cli.auth import resolve_api_key_provider_credentials

    try:
        return bool(resolve_api_key_provider_credentials(provider).get("api_key"))
    except Exception:  # unknown or non-API-key provider: treat as unavailable
        logger.debug("credential probe failed for %s", provider, exc_info=True)
        return False


class CompletionClient(Protocol):
    def complete(self, route: Route, messages: list[dict[str, str]], timeout: float) -> str: ...


class MeuCompletionClient:
    """One stateless ``call_llm`` per request; the Reviewer never shares Coder state."""

    def complete(self, route: Route, messages: list[dict[str, str]], timeout: float) -> str:
        from agent.auxiliary_client import call_llm, extract_content_or_reasoning

        try:
            response = call_llm(task="coding_engine", provider=route.provider, model=route.model,
                                messages=messages, temperature=0, timeout=timeout)
        except Exception as exc:  # any provider failure is a controlled ProviderError
            logger.warning("coding engine: %s call failed: %s", route, type(exc).__name__, exc_info=True)
            raise ProviderError(f"{route} failed: {type(exc).__name__}") from None
        return extract_content_or_reasoning(response, max_reasoning_chars=0) or ""


@dataclass(frozen=True)
class CallRecord:
    role: str
    route: str
    attempts: int
    seconds: float
    ok: bool
    error: str = ""


@dataclass
class ProviderSession:
    client: CompletionClient
    routes: CodingRoutes
    timeout: float = DEFAULT_TIMEOUT
    max_format_retries: int = 1
    calls: list[CallRecord] = field(default_factory=list)

    def ask(self, role: str, route: Route, system: str, payload: dict[str, Any],
            validate: Callable[[dict[str, Any]], Any]):
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)}]
        started = time.perf_counter()
        attempts = 0
        last_error = ""
        while attempts <= self.max_format_retries:
            attempts += 1
            try:
                text = self.client.complete(route, messages, self.timeout)
            except ProviderError as exc:
                self._record(role, route, attempts, started, False, str(exc))
                raise
            try:
                result = validate(parse_json_object(text))
            except SchemaError as exc:
                last_error = str(exc)
                messages = [*messages, {"role": "assistant", "content": text[:4_000]},
                            {"role": "user", "content": "Your reply was rejected: " + last_error
                             + ". Reply again with ONLY the JSON object described in the instructions."}]
                continue
            self._record(role, route, attempts, started, True)
            return result
        self._record(role, route, attempts, started, False, last_error)
        raise SchemaError([last_error or "invalid response"])

    def _record(self, role, route, attempts, started, ok, error="") -> None:
        self.calls.append(CallRecord(role, str(route), attempts, round(time.perf_counter() - started, 3), ok,
                                     error[:300]))


# ── prompts ─────────────────────────────────────────────────────────────────

_COMMON = ("You are part of a coding pipeline. Reply with ONE JSON object and nothing else. "
           "Paths are repository-relative with forward slashes. Never include shell commands, "
           "approvals or keys named command/run/approved; they are rejected.")

ARCHITECT_SYSTEM = _COMMON + (
    " Role: Architect. Plan only. Schema: {\"summary\": str, \"files_to_change\": [existing path], "
    "\"new_files\": [path], \"symbols_to_change\": [str], \"steps\": [str], "
    "\"checks\": [{\"kind\": \"syntax\"|\"lint\"|\"unit_test\"|\"build\", \"targets\": [path]}], "
    "\"assumptions\": [str], \"unresolved_questions\": [str], \"risk\": \"low\"|\"medium\"|\"high\"}. "
    "Keep the change minimal; never plan protected files. Use unresolved_questions ONLY when the task "
    "cannot be implemented without the answer (it stops the task); for style or detail choices pick the "
    "simplest option consistent with the existing code and record it in assumptions.")

CODER_SYSTEM = _COMMON + (
    " Role: Coder. Propose edits for the approved plan only. Schema: {\"operations\": [{\"path\": str, "
    "\"action\": \"update\"|\"create\", \"description\": str, <payload>}], \"assumptions\": [str], "
    "\"expected_tests\": [path], \"notes\": str}. Payload for action=update with strategy "
    "search_replace: \"search\" (exact existing text) and \"replace\"; v4a_patch or unified_diff: "
    "\"patch\"; whole_file: \"content\". action=create always uses \"content\" (whole file).")

REVIEWER_SYSTEM = _COMMON + (
    " Role: independent Reviewer. Judge whether the proposal and, when given, the actual diff and "
    "test results correctly and minimally implement the task within the plan. Schema: "
    "{\"verdict\": \"pass\"|\"fix\"|\"block\", \"findings\": [{\"category\": \"correctness\"|"
    "\"missing_requirement\"|\"regression\"|\"risky_change\"|\"scope_violation\"|\"test_gap\"|"
    "\"unexpected_file\", \"severity\": \"pass\"|\"fix\"|\"block\", \"message\": str, \"path\": str?, "
    "\"repair\": str?}]}. Use fix with a concrete repair for defects; block for unsafe changes.")


def _context_payload(context: TaskContext, budget: int) -> list[dict[str, Any]]:
    items, used = [], 0
    for item in context.bundle.items:
        if used + item.size > budget:
            break
        used += item.size
        items.append({"path": item.path, "lines": [item.start_line, item.end_line], "excerpt": item.excerpt})
    return items


def _plan_payload(plan: ImplementationPlan) -> dict[str, Any]:
    return {"summary": plan.summary, "files_to_change": plan.files_to_change, "new_files": plan.new_files,
            "symbols_to_change": plan.symbols_to_change, "steps": plan.steps,
            "files_untouched": plan.files_untouched, "risk": plan.risk.value,
            "checks": [{"kind": c.kind.value, "targets": c.targets} for c in plan.test_plan.checks]}


def _task_payload(context: TaskContext) -> dict[str, Any]:
    task = context.task
    return {"description": task.description, "explicit_files": task.explicit_files,
            "protected_paths": task.constraints.protected_paths,
            "allow_new_files": task.constraints.allow_new_files, "max_files": task.constraints.max_files,
            "recent_diff": (task.recent_diff or "")[:4_000]}


# ── the three Phase 2 model protocols ────────────────────────────────────────


class ProviderPlanningModel:
    def __init__(self, session: ProviderSession, context_chars: int = 16_000) -> None:
        self.session = session
        self.context_chars = context_chars

    def plan(self, request: PlanningRequest) -> ImplementationPlan:
        payload = {"task": _task_payload(request.context), "draft_plan": _plan_payload(request.draft),
                   "context": _context_payload(request.context, self.context_chars)}
        try:
            response = self.session.ask("architect", self.session.routes.architect, ARCHITECT_SYSTEM,
                                        payload, validate_architect)
        except (ProviderError, SchemaError) as exc:
            raise PlanningError("architect model failed", (str(exc),)) from None
        checks = list(request.draft.test_plan.checks)
        known = {c.key for c in checks}
        for kind, targets in response.checks:
            spec = CheckSpec(kind, f"{kind.value} requested by the architect", targets)
            if spec.key not in known:
                checks.append(spec)
                known.add(spec.key)
        from meu_coding.scope import is_protected
        targets = {*response.files_to_change, *response.new_files}
        untouched = tuple(path for path in request.draft.files_untouched
                          if path not in targets or is_protected(path, request.task.constraints.protected_paths))
        return replace(
            request.draft, files_untouched=untouched, summary=response.summary or request.draft.summary,
            files_to_change=response.files_to_change, new_files=response.new_files,
            symbols_to_change=response.symbols_to_change, steps=response.steps,
            test_plan=TestPlan(tuple(checks)), risk=max_risk([request.draft.risk, response.risk]),
            impact=None, assumptions=(*request.draft.assumptions, *response.assumptions),
            unresolved_questions=response.unresolved_questions,
        )


class ProviderCodingModel:
    def __init__(self, session: ProviderSession) -> None:
        self.session = session
        self.last_route: Route | None = None
        self.last_routing: dict[str, Any] = {}
        self.simple_failures = 0

    def route_for(self, request: CodingRequest) -> Route:
        """``routing_policy.decide_coder_workload``: coding.simple only for small, low-risk first
        attempts with a modest context; strong otherwise, and after repeated simple failures.
        The decision only picks a model; approvals and review are unchanged."""
        from meu_coding.routing_policy import RoutingSignals, classify, decide_coder_workload

        routes = self.session.routes
        classification = classify(request.plan)
        bundle = getattr(request.context, "bundle", None)
        context_chars = sum(len(i.excerpt) for i in bundle.items) if bundle is not None else 0
        signals = RoutingSignals(classification, context_chars,
                                 len(request.plan.files_to_change) + len(request.plan.new_files),
                                 request.repair.attempt if request.repair is not None else 0, self.simple_failures,
                                 getattr(request.task, "milestone_kind", ""))
        decision = decide_coder_workload(signals)
        simple = decision.workload == "coding.simple" and routes.coder_simple is not None
        route = routes.coder_simple if simple else routes.coder
        workload = "coding.simple" if simple else "coding.complex"
        self.last_routing = {"complexity": classification.complexity.value, "workload": workload,
                             "route": str(route), "reasons": list(decision.reasons),
                             "repair": request.repair is not None, "escalated": decision.escalated,
                             "context_chars": context_chars, "simple_failures": self.simple_failures}
        return route

    def propose(self, request: CodingRequest) -> CoderOutput:
        output = self._propose_once(request)
        # Controlled escalation: a failing simple route is retried once, then the strong route takes over.
        while (not output.operations and output.notes.startswith("coder model failed")
               and self.last_routing.get("workload") == "coding.simple"):
            self.simple_failures += 1
            output = self._propose_once(request)
        return output

    def _propose_once(self, request: CodingRequest) -> CoderOutput:
        route = self.route_for(request)
        self.last_route = route
        payload = {"task": _task_payload(request.context), "plan": _plan_payload(request.plan),
                   "strategy": request.strategy.strategy.value,
                   "context": _context_payload(request.context, request.max_context_chars)}
        if request.repair is not None:
            payload["repair"] = {"attempt": request.repair.attempt,
                                 "instructions": request.repair.review.repair_instructions,
                                 "previous_files": request.repair.previous.affected_files}
        strategy = request.strategy.strategy
        try:
            response = self.session.ask("coder", route, CODER_SYSTEM, payload,
                                        lambda data: validate_coder(data, strategy))
        except (ProviderError, SchemaError) as exc:
            return CoderOutput((), notes=f"coder model failed: {exc}")
        return CoderOutput(response.operations, response.assumptions, response.expected_tests, response.notes)


class ProviderReviewModel:
    def __init__(self, session: ProviderSession, context_chars: int = 12_000) -> None:
        self.session = session
        self.context_chars = context_chars

    def review(self, request: ReviewRequest) -> tuple[ReviewFinding, ...]:
        payload = {
            "task": _task_payload(request.context), "plan": _plan_payload(request.plan),
            "proposal": [{"path": op.path, "action": op.action.value, "strategy": op.strategy.value,
                          "description": op.description, "search": op.search, "replace": op.replace,
                          "content": op.content, "patch": op.patch} for op in request.proposal.operations],
            "actual_diff": (request.diff or "")[:30_000],
            "test_results": [{"check": r.key, "status": r.status.value, "output": r.output[-2_000:]}
                             for r in request.test_results],
            "context": _context_payload(request.context, self.context_chars),
        }
        try:
            return self.session.ask("reviewer", self.session.routes.reviewer, REVIEWER_SYSTEM, payload,
                                    validate_reviewer)
        except (ProviderError, SchemaError) as exc:
            return (ReviewFinding(FindingCategory.CORRECTNESS, ReviewStatus.BLOCK,
                                  f"independent model review unavailable: {exc}"),)


@dataclass(frozen=True)
class ProviderModels:
    planning: ProviderPlanningModel
    coding: ProviderCodingModel
    review: ProviderReviewModel


def provider_models(routes: CodingRoutes, client: CompletionClient | None = None,
                    timeout: float = DEFAULT_TIMEOUT) -> ProviderModels:
    """One session per role, so the Reviewer never shares Coder state or call history."""
    client = client or MeuCompletionClient()
    return ProviderModels(
        planning=ProviderPlanningModel(ProviderSession(client, routes, timeout)),
        coding=ProviderCodingModel(ProviderSession(client, routes, timeout)),
        review=ProviderReviewModel(ProviderSession(client, routes, timeout)),
    )
