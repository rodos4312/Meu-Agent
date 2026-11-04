"""Let the parent LLM plan work through the existing delegation contract."""

from typing import Any, Mapping

from agent.delegation_provider import DelegationProvider, DelegationRouteError

from .planning import validate_plan
from .routing import DEEPSEEK_BACKEND, GENERAL_BACKEND, WORKLOADS, select_deepseek_model, select_model

_FILE_TOOLS = ("read_file", "write_file", "patch", "search_files")


class MeuCoordinator(DelegationProvider):
    def __init__(self, *, general: bool = False) -> None:
        self.general = general

    @property
    def name(self) -> str:
        return GENERAL_BACKEND if self.general else DEEPSEEK_BACKEND

    @property
    def display_name(self) -> str:
        return "Meu Coordinator · General" if self.general else "Meu Coordinator · DeepSeek"

    @property
    def summary(self) -> str:
        if self.general:
            return "Pick models by task from the session's provider and check parallel write scopes."
        return "For DeepSeek sessions: use Flash for routine and visual work, Pro for harder work."

    def task_parameters(self, config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "workload": {
                "type": "string", "enum": list(WORKLOADS),
                "description": "Required. Assess the actual subtask, not its length: routine = bounded extraction, "
                "lookup or mechanical edits; standard = ordinary implementation or synthesis; complex = architecture, "
                "difficult debugging or critical review; vision = interpreting images or screenshots.",
            },
            "acceptance": {"type": "string", "description": "Required. State what to check and the expected result or "
                           "evidence for a pass. Example: import two tasks with the same ID and confirm exactly one remains."},
            "parallel_safe": {"type": "boolean", "description": "Required. True only if this task needs no sibling's "
                              "result and can run independently in this call. Dependent work goes in later calls."},
            "tool_access": {"type": "string", "enum": ["inherit", "files_only"],
                            "description": "Choose files_only whenever the user restricts a helper to file tools. "
                            "The runtime enforces this choice. Otherwise inherit the parent tool policy (default)."},
            "write_paths": {"type": "array", "items": {"type": "string"},
                            "description": "Required. Project-relative files/directories this helper may change; "
                            "[] for read-only work, ['.'] for the whole project. Include the same scope in goal/context. "
                            "Overlapping write scopes cannot run in one batch."},
        }

    def description(self, config: Mapping[str, Any]) -> str:
        return (
            "Meu coordination: handle a straightforward request yourself when you can complete and check it in "
            "one short pass. For larger work, separate deliverables by dependency and give each an acceptance "
            "check. Delegate independent work that can proceed while you do something else, or work that needs "
            "a separate specialist. Use tasks=[...] even for one helper; supply workload, acceptance, "
            "parallel_safe and write_paths for EVERY task. You, the parent, assess complexity using the task's "
            "meaning; do not classify by keywords alone. Keep dependent work sequential: "
            "wait for prerequisite results, then pass their concrete artifacts/evidence in the next task's context. "
            "Set tool_access=files_only when the user restricts a helper to file tools. "
            "The coordinator passes acceptance checks and permitted write paths to every helper. Workers share "
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
        if workload not in WORKLOADS:
            raise DelegationRouteError("Set workload to routine, standard, complex or vision for this subtask.")
        parent_route = config.get("parent_route") or {}
        model = (select_model(workload, parent_route, self.settings(config).get("models"))
                 if self.general else select_deepseek_model(workload, parent_route))
        paths = task.get("write_paths", [])
        scope = ", ".join(paths) if paths else "Read-only: do not modify project files."
        route = {"model": model, "label": f"{workload} · {model or 'session model'}", "fallback_providers": [],
                "instructions": f"Coordinator task contract\nWrite scope: {scope}\n"
                f"Acceptance checks: {task.get('acceptance', '')}\n"
                "Return the work/artifact locations, checks actually run and their results, and any unresolved issues. "
                "Do not claim an unrun check passed. Stay inside this task's write scope."}
        if task.get("tool_access") == "files_only":
            route["allowed_tools"] = list(_FILE_TOOLS)
        return route


def register(ctx) -> None:
    coordinator = MeuCoordinator()
    ctx.register_delegation_provider(coordinator)
    ctx.register_delegation_provider(MeuCoordinator(general=True))
    # Minimal first-use routing registrars intentionally expose only the provider.
    # Session tool discovery uses the full plugin context and owns tool lifetime.
    if hasattr(ctx, "register_tool"):
        from .project_tool import register as register_projects
        register_projects(ctx, coordinator.task_parameters({}))
