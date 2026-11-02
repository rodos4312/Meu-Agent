"""Let the parent LLM plan work through the existing delegation contract."""

from typing import Any, Mapping

from agent.delegation_provider import DelegationProvider, DelegationRouteError

from .planning import validate_plan


class MeuCoordinator(DelegationProvider):
    @property
    def name(self) -> str:
        return "meu_coordinator"

    @property
    def display_name(self) -> str:
        return "Meu Coordinator"

    @property
    def summary(self) -> str:
        return "Plan each task: Flash for routine/visual work, Pro for complex work; check parallel write scopes."

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "workload": {
                "type": "string", "enum": ["routine", "complex", "vision"],
                "description": "Required. Assess the actual subtask, not its length: routine = bounded extraction, "
                "lookup, mechanical edits; complex = architecture, nontrivial code, debugging or critical review; "
                "vision = interpreting images/screenshots (Flash supports images).",
            },
            "acceptance": {"type": "string", "description": "Required. Concrete evidence/checks needed to accept the result. "
                           "Also include these checks in the task goal/context sent to the helper."},
            "parallel_safe": {"type": "boolean", "description": "Required. True only if this task needs no sibling's "
                              "result and can run independently in this call. Dependent work goes in later calls."},
            "write_paths": {"type": "array", "items": {"type": "string"},
                            "description": "Required. Project-relative files/directories this helper may change; "
                            "[] for read-only work, ['.'] for the whole project. Include the same scope in goal/context. "
                            "Overlapping write scopes cannot run in one batch."},
        }

    def description(self, config: Mapping[str, Any]) -> str:
        return (
            "Meu coordination: first break the request into small deliverables with dependencies and acceptance "
            "checks. Delegate only when it helps. Use tasks=[...] even for one helper; supply workload, acceptance, "
            "parallel_safe and write_paths for EVERY task. You, the parent, assess complexity using the task's "
            "meaning; do not send every task to Pro or classify by keywords alone. Keep dependent work sequential: "
            "wait for prerequisite results, then pass their concrete artifacts/evidence in the next task's context. "
            "Copy the acceptance checks and permitted write paths into each helper's goal/context. Workers share "
            "the project unless worktree isolation is configured; avoid conflicting edits. Inspect results and run "
            "the requested checks before calling the project complete. If a routine result fails its checks, "
            "reassign that specific task as complex with the failure evidence, rather than repeating blindly. "
            "Use an independent complex reviewer for consequential changes when useful; the parent integrates "
            "and reports verified results and remaining uncertainty. Model selection is fixed for each child; "
            "there is no additional planner API call. Existing stop, progress and concurrency limits still apply."
        )

    def validate_tasks(self, tasks: list[dict[str, Any]], config: Mapping[str, Any]) -> None:
        validate_plan(tasks)

    def route_task(self, task: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        workload = task.get("workload")
        if workload not in {"routine", "complex", "vision"}:
            raise DelegationRouteError("Set workload to routine, complex or vision for this subtask.")
        model = "deepseek-v4-pro" if workload == "complex" else "deepseek-flash"
        paths = task.get("write_paths", [])
        scope = ", ".join(paths) if paths else "Read-only: do not modify project files."
        return {"provider": "deepseek", "model": model,
                "label": f"{workload} · {model}", "fallback_providers": [],
                "instructions": f"Coordinator task contract\nWrite scope: {scope}\n"
                f"Acceptance checks: {task.get('acceptance', '')}\n"
                "Return the work/artifact locations, checks actually run and their results, and any unresolved issues. "
                "Do not claim an unrun check passed. Stay inside this task's write scope."}


def register(ctx) -> None:
    ctx.register_delegation_provider(MeuCoordinator())
