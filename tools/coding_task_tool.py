"""Thin Chat adapter to the SAME profile-scoped CodingTaskService used by RPC."""
from __future__ import annotations

import json
import threading
import time

from tools.registry import registry

_STAGES = {"analyzing": "Ανάλυση έργου", "planning": "Σχεδιασμός", "coding": "Πρόταση κώδικα",
           "reviewing": "Έλεγχος πρότασης", "executing": "Εκτέλεση σε ασφαλές worktree",
           "testing": "Εκτέλεση ελέγχων", "reviewing_diff": "Έλεγχος αλλαγών",
           "awaiting_approval": "Αναμονή έγκρισης", "awaiting_keep_reject": "Αποτελέσματα έτοιμα για αξιολόγηση"}


def _project(task_id: str, project_name: str = "") -> str:
    from tools.project_tools import project_list, project_switch
    from meu_coding.task_service import TaskError

    projects = json.loads(project_list(task_id=task_id))
    if project_name:
        matches = [p for p in projects["projects"] if p["name"].casefold() == project_name.strip().casefold()]
        if len(matches) != 1 or not matches[0].get("primary_path"):
            raise TaskError("The named project must match one existing project exactly; no path was guessed.")
        selected = json.loads(project_switch(matches[0]["id"], task_id=task_id))
        if not selected.get("success"):
            raise TaskError(selected.get("error", "Could not select the existing project."))
        return selected["primary_path"]
    active = [p for p in projects["projects"] if p["id"] == projects["active_id"]]
    if not active or not active[0].get("primary_path"):
        from tools.terminal_tool import _get_env_config, resolve_task_overrides
        overrides = resolve_task_overrides(task_id)
        if "cwd_source" in overrides:
            return str((overrides.get("cwd") if overrides["cwd_source"] == "session"
                        else overrides.get("host_workspace")) or "")
        cwd = _get_env_config().get("cwd") or ""
        return str(cwd) if cwd not in {".", "./", "auto", "cwd", "~"} else ""
    return active[0]["primary_path"]


def _chat_workflow(project: str) -> dict | None:
    """A missing Git baseline is a routing outcome, not a failed user request."""
    from pathlib import Path
    from meu_coding.workspace import WorkspaceError, read_identity

    if project and not Path(project).is_dir():
        from meu_coding.task_service import TaskError
        raise TaskError("This conversation's workspace is unavailable; no task was started.")
    try:
        if not project:
            raise WorkspaceError("No workspace selected")
        read_identity(project)
    except WorkspaceError:
        return {
            "workflow": "chat", "workspace": project or None, "engine_task_started": False,
            "notice": "This workspace has no usable Git baseline for an isolated engine task. "
                      "Continue the user's goal in this chat with ordinary tools and installed skills. "
                      "For a new project create a named subfolder; do not overwrite unrelated files. "
                      "Do not ask the user to configure Git or open another page. "
                      "Do not initialize or repair Git just to enable the engine. "
                      "Existing tool approvals still apply. Build, check and link the real deliverables.",
        }
    return None


def _result(view: dict, *, notice: str = "") -> dict:
    # Commit preview secrets and unrelated remote operations never enter model context.
    keys = ("task_id", "project", "description", "stage", "history", "error", "restored",
            "plan", "approval", "execution", "result", "cleanup", "decisions")
    result = {key: view[key] for key in keys if key in view}
    result["notice"] = notice or ("Show the actual worktree folder, changed files and test results in this chat. The result is preserved for review; the parent remains unchanged. Do not force an extra Keep/Reject question to deliver it. Use review_result if the user wants to keep or discard it. No commit, push or merge."
                                  if view["stage"] == "awaiting_keep_reject" else "")
    return result


def _follow(service, view: dict, session_id: str, *, wait_seconds: float = 90) -> dict:
    from agent.tool_progress_relay import current_tool_progress
    from tools.approval_human_wait import activity_heartbeat
    from tools.coding_task_approval import ask_coding_approval
    from tools.interrupt import is_interrupted
    from meu_coding.task_service import BUSY_STAGES

    progress = current_tool_progress()
    heartbeat = activity_heartbeat("coding task")
    deadline = time.monotonic() + wait_seconds
    busy = {stage.value for stage in BUSY_STAGES}
    seen = None
    waiter = threading.Event()
    while True:
        stage = view["stage"]
        if stage != seen:
            if progress:
                progress(0, None, f"{_STAGES.get(stage, stage)} · {view['task_id'][:8]}")
            seen = stage
        if is_interrupted():
            return _result(view, notice="Chat monitoring interrupted. Task state is preserved; use status before continuing.")
        if stage == "awaiting_approval" and not view.get("restored"):
            waiting_at = time.monotonic()
            choice = ask_coding_approval(view)
            deadline += time.monotonic() - waiting_at
            if choice == "unanswered":
                return _result(view, notice="Human approval was not received. Nothing was executed. Continue to request approval again.")
            proposal = view["approval"]
            view = service.decide(view["task_id"], approval_id=proposal["approval_id"],
                                  fingerprint=proposal["fingerprint"], approve=choice == "approve",
                                  approver="chat:" + session_id, source="chat")
            continue
        if stage not in busy or time.monotonic() >= deadline:
            return _result(view)
        heartbeat()
        waiter.wait(0.15)
        view = service.chat_task(session_id, view["task_id"])


def _handle_coding(args, *, task_id=None, session_id=None, turn_id=None, tool_call_id=None, parent_agent=None):
    from meu_coding.service_registry import current_service
    from meu_coding.task_service import TaskError

    action = args.get("action")
    if action not in {"start", "status", "continue", "review_result"}:
        return json.dumps({"error": "action must be start, status, continue or review_result"})
    if not session_id or (action == "start" and not task_id):
        return json.dumps({"error": "Trusted conversation identity is unavailable; no task started."})
    try:
        if action != "status":
            from tools.terminal_tool import _get_env_config, resolve_task_overrides
            overrides = resolve_task_overrides(task_id)
            backend = overrides.get("env_type") or _get_env_config()["env_type"]
            if backend != "local":
                raise TaskError("Coding tasks currently require this device's local workspace. "
                                "The selected execution backend is not local; nothing was started.")
        if action == "start":
            if not (args.get("description") or "").strip():
                raise TaskError("Describe the coding task first.")
            project = _project(task_id, args.get("project_name", ""))
            direct = _chat_workflow(project)
            if direct is not None:
                return json.dumps(direct, ensure_ascii=False)
        service = current_service()
        if action == "start":
            view = service.start_chat(args.get("description", ""), project, session_id,
                                      turn_id or tool_call_id or "", tuple(args.get("files") or ()))
        else:
            view = service.chat_task(session_id, args.get("coding_task_id", ""))
        if action == "review_result":
            from tools.coding_result_choice import ask_result_choice, result_fingerprint
            if view["stage"] != "awaiting_keep_reject":
                return json.dumps(_result(view, notice="This result is not awaiting a new decision."), ensure_ascii=False)
            fingerprint = result_fingerprint(view)
            choice = ask_result_choice(view, getattr(parent_agent, "clarify_callback", None))
            if choice == "unanswered":
                return json.dumps(_result(view, notice="No explicit result choice received; result preserved for review."), ensure_ascii=False)
            view = service.decide_chat_result(session_id, view["task_id"], choice, fingerprint)
            return json.dumps(_result(view, notice="Result decision recorded. The parent project remains unchanged. No commit, push or merge."), ensure_ascii=False)
        result = _result(view) if action == "status" else _follow(service, view, session_id)
        return json.dumps(result, ensure_ascii=False)
    except (TaskError, OSError, ValueError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


registry.register(
    name="coding_task", toolset="project", handler=_handle_coding,
    schema={"name": "coding_task", "description": (
        "Optional isolated Coding Engine for substantial changes in an existing local Git project. "
        "Choose it automatically when useful; new projects, small programs and straightforward edits "
        "can use the ordinary development workflow. No separate Coding page or role selection needed. "
        "start uses this chat's selected project or current workspace, and resumes the same task on retry. "
        "A workflow='chat' result starts no engine task: continue with the ordinary workflow, without Git setup. "
        "continue follows the task, requests its exact human approval and returns real progress/tests/results. "
        "Keep all progress and deliverables in this chat. At awaiting_keep_reject the result is already "
        "preserved in its worktree; show its actual folder/files and checks without a mandatory extra question. "
        "review_result is an optional human Keep/Reject choice; Keep never copies to the parent. "
        "Do not bypass a pending engine task with direct edits or a separate clarification approval. "
        "status only reads. Never claim pending/interrupted work is complete. No commit/push/merge actions."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["start", "status", "continue", "review_result"]},
            "project_name": {"type": "string", "description": "Exact existing project name explicitly named by the user; omit to use this chat's selection. Never guess a path."},
            "description": {"type": "string", "description": "Development goal for start."},
            "files": {"type": "array", "items": {"type": "string"}, "description": "Optional project-relative focus files."},
            "coding_task_id": {"type": "string", "description": "Optional existing task from this conversation."}},
            "required": ["action"]}},
)
