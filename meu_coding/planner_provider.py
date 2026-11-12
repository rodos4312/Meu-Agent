"""The AutonomousPlanner's model, on MEU's own provider stack (workload ``coding.planner``).

One ``call_llm`` per request through ``provider_adapter.MeuCompletionClient`` and the shared
``ProviderSession`` (credentials, retries and fallbacks are MEU's). The reply is parsed and
validated by ``autonomous_planner``; it is data and cannot select a command, approve anything
or touch a file.
"""

from __future__ import annotations

from typing import Any

from meu_coding.autonomous_planner import KINDS, MAX_MILESTONES, REVISION_OPS, PlannerError
from meu_coding.provider_adapter import (
    CodingRoutes,
    MeuCompletionClient,
    ProviderError,
    ProviderSession,
    Route,
)
from meu_coding.schemas import SchemaError

PLANNER_SYSTEM = (
    "You are the roadmap planner of a coding pipeline. Reply with ONE JSON object and nothing else. "
    "You only plan: every milestone later becomes a separate coding task that the user must approve. "
    "Schema: {\"milestones\": [{\"id\": \"m1\", \"title\": str, \"objective\": str, \"depends_on\": [id], "
    "\"expected_areas\": [repository-relative path or directory], \"acceptance_criteria\": [str], "
    "\"tests\": [str], \"risk\": \"low\"|\"medium\"|\"high\", \"complexity\": \"simple\"|\"complex\", "
    f"\"kind\": {'|'.join(KINDS)}}}]}}. At most {MAX_MILESTONES} milestones, no dependency cycles, "
    "small verifiable steps, tests in every implementation milestone, a final review milestone. "
    "Stay inside the goal. Items listed as deferred work belong to other phases: never plan them "
    "unless the goal explicitly names them. Memory notes are hints; the repository listing wins."
)

REVISION_SYSTEM = (
    "You maintain a coding roadmap after a milestone finished. Reply with ONE JSON object: "
    "{\"reason\": str, \"operations\": [{\"op\": " + "|".join(REVISION_OPS) + ", \"milestone\": id, "
    "\"detail\": str}], \"milestones\": [the full proposed milestone list, same schema as the roadmap]}. "
    "Use [{\"op\": \"keep\"}] when nothing should change. Never change or remove milestones that are "
    "APPROVED, IN_PROGRESS, DONE or REJECTED. Every change is shown to the user for approval."
)


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SchemaError(["the reply must be a JSON object"])
    return data


class ProviderPlannerModel:
    def __init__(self, route: Route, client=None, timeout: float = 180.0) -> None:
        self.route = route
        routes = CodingRoutes(route, route, route)
        self.session = ProviderSession(client or MeuCompletionClient(), routes, timeout)

    def _ask(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.session.ask("planner", self.route, system, payload, _validate)
        except (ProviderError, SchemaError) as exc:
            raise PlannerError(f"planner model failed: {exc}") from None

    def propose_roadmap(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        return self._ask(PLANNER_SYSTEM, {"goal": goal, "context": context})

    def propose_revision(self, roadmap: dict[str, Any], finished: dict[str, Any]) -> dict[str, Any]:
        return self._ask(REVISION_SYSTEM, {"roadmap": {k: roadmap[k] for k in ("goal", "milestones", "revision")},
                                           "finished_milestone": finished})


def meu_planner() -> ProviderPlannerModel:
    """The planner route from existing settings (Models by workload, else the main model)."""
    from hermes_cli.config import load_config_readonly

    from meu_coding.routing_policy import resolve_workloads

    routes = resolve_workloads(load_config_readonly())
    chosen = routes.get("coding.planner")
    if chosen is None:
        raise PlannerError("No model is configured: choose a main model or Models by workload in Settings.")
    return ProviderPlannerModel(Route(chosen.provider, chosen.model))
