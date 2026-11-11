"""Coding approvals for the paired phone, on the existing revocable, pinned, profile-scoped listener.

One authority: the phone calls the SAME per-profile ``CodingTaskService`` the desktop uses
(``meu_coding.service_registry``), so a phone decision consumes the exact approval object the
desktop shows, once; whichever device decides first wins and the other gets a refusal.

Identity is the pairing's own ``device_id`` (server-side), never a value from the request
body. The phone may approve or reject a proposal, keep or reject an executed result, and
approve a remote push / PR creation / merge that the PC previewed (naming that preview's exact
fingerprint, each its own single-use approval). It cannot start tasks, commit, integrate, or
create a remote preview, and nothing remote runs without such an approval. Views are sanitized: project names
instead of host paths, branch names instead of worktree paths, diff summaries capped by
default with explicit per-file expansion.
"""

from __future__ import annotations

import asyncio
import posixpath
import re
from typing import Any

from aiohttp import web

MAX_LINES_PER_FILE = 40
MAX_SUMMARY_LINES = 200
MAX_EXPANDED_LINES = 2_000
_TASK_ID = re.compile(r"^[0-9a-f]{32}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")

MOBILE_LABELS = {
    "analyzing": "Preparing on PC", "planning": "Preparing on PC", "coding": "Preparing on PC",
    "reviewing": "Preparing on PC", "awaiting_approval": "Needs your approval", "executing": "Coding on PC",
    "testing": "Testing", "reviewing_diff": "Reviewing result", "awaiting_keep_reject": "Needs keep/reject",
    "kept": "Kept", "ready_to_commit": "Kept — commit on PC", "committed": "Ready to integrate",
    "integration_preview": "Integration on PC", "integrating": "Integration on PC", "integrated": "Integrated",
    "rejected": "Rejected", "blocked": "Blocked", "failed": "Failed", "interrupted": "Interrupted",
}


_REMOTE_KINDS = ("push", "pr", "merge")
_SHA_FIELDS = ("source_commit", "new_sha", "expected_remote_sha", "source_sha", "target_sha", "remote_sha",
               "merge_commit_sha")


def _short(value: str) -> str:
    return value[:12] if isinstance(value, str) else ""


def _remote_preview(kind: str, preview: dict[str, Any]) -> dict[str, Any]:
    keep = {"push": ("repository", "remote", "source_branch", "destination_branch", "refspec", "remote_exists",
                     "force_required", "status", "reason", "changed_files", "risk"),
            "pr": ("repository", "source_branch", "target_branch", "title", "body", "commits", "changed_files",
                   "risk", "limitations"),
            "merge": ("repository", "pr_number", "target_branch", "method", "allowed_methods", "checks", "reviews",
                      "changed_files", "target_drift", "conflicts", "reviewer", "risk", "status", "reasons")}[kind]
    out = {k: preview[k] for k in keep if k in preview}
    out.update({k: _short(preview[k]) for k in _SHA_FIELDS if preview.get(k)})
    out["fingerprint"] = preview.get("fingerprint", "")
    return out


def _remote_view(remote: dict[str, Any] | None, actions: dict[str, Any]) -> dict[str, Any] | None:
    """Repository identity, refs, short SHAs, checks and reviews — never URLs with paths or credentials."""
    if not remote:
        return None
    info = remote.get("info") or {}
    out: dict[str, Any] = {"state": remote.get("state", ""), "label": remote.get("state_label", ""),
                           "repository": info.get("identity", "") if info.get("is_github") else "",
                           "available": bool(info.get("available")), "reason": info.get("reason", ""),
                           "pending": [k for k in remote.get("pending", []) if k in _REMOTE_KINDS],
                           "approve": {"push": bool(actions.get("push_approve")),
                                       "pr": bool(actions.get("pr_create_approve")),
                                       "merge": bool(actions.get("merge_approve"))}}
    for kind in _REMOTE_KINDS:
        if kind in out["pending"] and remote.get(f"{kind}_preview"):
            out[f"{kind}_preview"] = _remote_preview(kind, remote[f"{kind}_preview"])
    if remote.get("pr"):
        pr = remote["pr"]
        out["pr"] = {"number": pr.get("number"), "url": pr.get("url", ""), "state": pr.get("state", ""),
                     "source_sha": _short(pr.get("source_sha", ""))}
    if remote.get("pr_status"):
        status = remote["pr_status"]
        out["pr_status"] = {k: status.get(k) for k in ("state", "merged", "draft", "mergeable", "head_drift",
                                                       "target_drift", "checks", "reviews")}
    if remote.get("merged"):
        out["merged"] = {"merge_commit": _short(remote["merged"].get("merge_commit_sha", "")),
                         "method": remote["merged"].get("method", ""),
                         "target_verified": bool(remote["merged"].get("target_verified"))}
    if remote.get("blocked"):
        out["blocked"] = remote["blocked"].get("reason", "")
    return out


def device_source(device_id: str | None) -> str:
    return "phone-" + (device_id or "legacy")


def _project_name(path: str) -> str:
    return posixpath.basename(str(path).replace("\\", "/").rstrip("/")) or "project"


def _diff_files(text: str) -> list[dict[str, Any]]:
    """Per-file change lines (headers dropped), from git or preview-style unified diffs."""
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    lines = (text or "").split("\n")
    for index, line in enumerate(lines):
        header = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        paired = line.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ ")
        if header or (paired and (current is None or current["hunks"])):
            path = header.group(2) if header else lines[index + 1][4:].removeprefix("b/")
            current = {"path": path, "additions": 0, "deletions": 0, "lines": [], "hunks": 0}
            files.append(current)
            continue
        if current is None or paired or (line.startswith("+++ ") and lines[index - 1].startswith("--- ")):
            continue
        if line.startswith("@@"):
            current["hunks"] += 1
        elif line.startswith("+"):
            current["additions"] += 1
        elif line.startswith("-"):
            current["deletions"] += 1
        else:
            continue
        current["lines"].append(line)
    return files


def diff_summary(text: str) -> dict[str, Any]:
    files, budget, truncated = [], MAX_SUMMARY_LINES, False
    for item in _diff_files(text):
        shown = item["lines"][:min(MAX_LINES_PER_FILE, max(budget, 0))]
        budget -= len(shown)
        cut = len(shown) < len(item["lines"])
        truncated = truncated or cut
        files.append({"path": item["path"], "additions": item["additions"], "deletions": item["deletions"],
                      "lines": shown, "truncated": cut})
    return {"files": files, "truncated": truncated}


def mobile_view(view: dict[str, Any]) -> dict[str, Any]:
    """Only what a decision needs; no host paths, keys or file contents beyond the diff."""
    plan = view.get("plan") or {}
    approval = view.get("approval") or {}
    execution = view.get("execution") or {}
    result = view.get("result") or {}
    actions = view.get("actions") or {}
    worktree_branch = (execution.get("worktree") or {}).get("branch") or result.get("worktree_branch") or ""
    out = {
        "task_id": view["task_id"], "project": _project_name(view.get("project", "")),
        "description": view.get("description", ""), "stage": view["stage"],
        "label": MOBILE_LABELS.get(view["stage"], view.get("stage_label", "")), "error": view.get("error", ""),
        "busy": bool(view.get("busy")), "restored": bool(view.get("restored")), "created_at": view.get("created_at"),
        "risk": plan.get("risk", ""), "summary": plan.get("summary", ""),
        "files": approval.get("target_files") or plan.get("files_to_change") or [],
        "tests_expected": [f"{c['kind']}: {', '.join(c['targets']) or 'new test'}" for c in plan.get("checks", [])],
        "actions": {"approve": bool(actions.get("approve")), "reject_proposal": bool(actions.get("reject_proposal")),
                    "keep": bool(actions.get("keep")), "reject": bool(actions.get("reject"))},
        "pc": {"online": True, "busy": bool(view.get("busy")), "worktree_branch": worktree_branch},
        "decisions": [{"decision": d.get("decision"), "source": d.get("source")} for d in view.get("decisions", [])],
    }
    remote = _remote_view(view.get("remote"), actions)
    if remote:
        out["remote"] = remote
        if any(remote["approve"].values()):
            out["label"] = "Needs remote approval"
    if approval:
        out["approval"] = {"approval_id": approval["approval_id"], "fingerprint": approval["fingerprint"],
                           "strategy": approval.get("strategy", ""),
                           "proposed": diff_summary(approval.get("proposed_diff", ""))}
    if execution:
        reviewer = execution.get("reviewer") or {}
        out["result"] = {"files_changed": execution.get("files_changed", []),
                         "additions": execution.get("additions", 0), "deletions": execution.get("deletions", 0),
                         "tests": [{"check": t["check"], "status": t["status"]} for t in execution.get("tests", [])],
                         "reviewer": {"verdict": reviewer.get("verdict", ""), "rationale": reviewer.get("rationale", "")},
                         "actual": diff_summary(execution.get("actual_diff", ""))}
    elif result:
        out["result"] = {"files_changed": result.get("changed_files", []), "additions": result.get("additions", 0),
                         "deletions": result.get("deletions", 0), "tests": result.get("tests", []),
                         "reviewer": {"verdict": result.get("reviewer_verdict", ""),
                                      "rationale": result.get("reviewer_rationale", "")},
                         "actual": {"files": [], "truncated": True}}
    return out


def _expanded(view: dict[str, Any], which: str, path: str) -> dict[str, Any]:
    text = ((view.get("approval") or {}).get("proposed_diff", "") if which == "proposed"
            else (view.get("execution") or {}).get("actual_diff", ""))
    for item in _diff_files(text):
        if item["path"] == path:
            lines = item["lines"][:MAX_EXPANDED_LINES]
            return {"path": path, "lines": lines, "truncated": len(lines) < len(item["lines"])}
    raise LookupError("no such file in this diff")


def _task_id(payload: dict[str, Any]) -> str:
    task_id = payload.get("task_id")
    if not isinstance(task_id, str) or not _TASK_ID.match(task_id):
        raise ValueError("invalid_task")
    return task_id


def operate(service, device_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    """The phone's coding operations. ``device_id`` comes from the pairing, never the body."""
    op = payload.get("op")
    source = device_source(device_id)
    if op == "list":
        return {"tasks": [{"task_id": r["task_id"], "project": _project_name(r["project"]),
                           "description": r["description"], "stage": r["stage"],
                           "label": MOBILE_LABELS.get(r["stage"], r["stage"]), "created_at": r["created_at"]}
                          for r in service.list()], "pc": {"online": True}}
    task_id = _task_id(payload)
    if op == "get":
        return {"task": mobile_view(service.get(task_id))}
    if op == "diff":
        which, path = payload.get("which"), payload.get("path")
        if which not in ("proposed", "actual") or not isinstance(path, str):
            raise ValueError("invalid_diff_request")
        return _expanded(service.get(task_id), which, path)
    if op == "decide":
        approval_id, fingerprint, decision = payload.get("approval_id"), payload.get("fingerprint"), payload.get("decision")
        if not isinstance(approval_id, str) or not isinstance(fingerprint, str) or not _FINGERPRINT.match(fingerprint) \
                or decision not in ("approve", "reject"):
            raise ValueError("invalid_decision")
        view = service.decide(task_id, approval_id=approval_id, fingerprint=fingerprint, approve=decision == "approve",
                              approver=source, device=source, source="mobile")
        return {"task": mobile_view(view)}
    if op == "keep":
        return {"task": mobile_view(service.keep(task_id, source="mobile"))}
    if op == "reject":
        return {"task": mobile_view(service.reject(task_id, source="mobile"))}
    if op == "remote_approve":
        kind, fingerprint = payload.get("kind"), payload.get("fingerprint")
        if kind not in _REMOTE_KINDS or not isinstance(fingerprint, str) or not _FINGERPRINT.match(fingerprint)                 or payload.get("confirmed") is not True:
            raise ValueError("invalid_remote_approval")
        return {"task": mobile_view(service.remote_approve(task_id, kind, fingerprint=fingerprint, confirmed=True,
                                                           source=source))}
    if op == "remote_refresh":
        return {"task": mobile_view(service.remote_refresh(task_id))}
    raise ValueError("invalid_coding_operation")


def run_in_profile(home: str, device_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Bind the profile's runtime scope (home, secrets, terminal) so work the service starts
    from this request inherits it, exactly like the desktop's profile-scoped RPC."""
    from meu_coding.service_registry import service_for_home
    from tui_gateway import server  # the facade the scope helper is bound to

    with server._session_profile_runtime_scope({"profile_home": home}):
        return operate(service_for_home(home), device_id, payload)


def mount(app, preview):
    async def handle(request):
        from meu_coding.task_service import TaskError

        try:
            payload = await preview._json(request)
            result = await asyncio.to_thread(run_in_profile, str(preview.authority.profile_id), preview.device_id,
                                             payload)
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except TaskError as error:
            return web.json_response({"status": "refused", "reason": str(error)[:300]}, status=409)
        except LookupError:
            raise web.HTTPNotFound() from None
        except (ValueError, KeyError, TypeError) as error:
            return web.json_response({"status": "refused", "reason": str(error)[:100]}, status=409)
    app.router.add_post("/meu/coding", handle)
