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
        raise TaskError("Choose an existing project in this conversation first. Do not guess a folder.")
    return active[0]["primary_path"]


def _result(view: dict, *, notice: str = "") -> dict:
    # Commit preview secrets and unrelated remote operations never enter model context.
    keys = ("task_id", "project", "description", "stage", "history", "error", "restored",
            "plan", "approval", "execution", "result")
    result = {key: view[key] for key in keys if key in view}
    result["notice"] = notice or ("Review the result; changes remain in the isolated worktree. No commit, push or merge."
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


def _handle_coding(args, *, task_id=None, session_id=None, turn_id=None, tool_call_id=None):
    from meu_coding.service_registry import current_service
    from meu_coding.task_service import TaskError

    action = args.get("action")
    if action not in {"start", "status", "continue"}:
        return json.dumps({"error": "action must be start, status or continue"})
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
        service = current_service()
        if action == "start":
            view = service.start_chat(args.get("description", ""), _project(task_id, args.get("project_name", "")), session_id,
                                      turn_id or tool_call_id or "", tuple(args.get("files") or ()))
        else:
            view = service.chat_task(session_id, args.get("coding_task_id", ""))
        result = _result(view) if action == "status" else _follow(service, view, session_id)
        return json.dumps(result, ensure_ascii=False)
    except (TaskError, OSError, ValueError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


registry.register(
    name="coding_task", toolset="project", handler=_handle_coding,
    schema={"name": "coding_task", "description": (
        "Use the existing Coding Engine for software development, bug fixes, features and code review "
        "in this chat's selected project. For a development request call start FIRST, before terminal, file discovery or repository repair. Choose it automatically; the user "
        "does not choose Architect/Coder/Reviewer. start creates or resumes the same task for a turn; "
        "continue follows this chat's latest task (or coding_task_id), requests exact human approval "
        "and returns real progress/tests/results. status only reads. Never claim completion from a "
        "pending/interrupted stage. Requires an existing local git project; GitHub and a PC connection "
        "are not required. Read-only analysis can use ordinary read tools. No commit/push/merge actions."),
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["start", "status", "continue"]},
            "project_name": {"type": "string", "description": "Exact existing project name explicitly named by the user; omit to use this chat's selection. Never guess a path."},
            "description": {"type": "string", "description": "Development goal for start."},
            "files": {"type": "array", "items": {"type": "string"}, "description": "Optional project-relative focus files."},
            "coding_task_id": {"type": "string", "description": "Optional existing task from this conversation."}},
            "required": ["action"]}},
)
