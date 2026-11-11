"""Read-only views of a coding task for the desktop (and future mobile) UI.

Everything here is built from objects the engine already produced: the plan, the pending
``ExecutionApprovalRequest`` (with its preview diff), the ``ExecutionResult`` (with the
actual worktree diff and check results), the review and impact reports. Nothing is
re-analysed, re-diffed or re-run to display it. Raw internals stay out of the default view;
``details`` carries timings, fingerprints and stage history for "View details".
"""

from __future__ import annotations

from typing import Any

MAX_DIFF_CHARS = 200_000
MAX_OUTPUT_CHARS = 4_000

STAGE_LABELS = {
    "analyzing": "Analyzing", "planning": "Planning", "coding": "Coding", "reviewing": "Reviewing",
    "awaiting_approval": "Awaiting approval", "executing": "Executing", "testing": "Testing",
    "reviewing_diff": "Reviewing diff", "awaiting_keep_reject": "Awaiting keep / reject", "kept": "Kept",
    "ready_to_commit": "Ready to commit", "committed": "Committed", "rejected": "Rejected",
    "blocked": "Blocked", "failed": "Failed", "committed_in_worktree": "Committed in worktree",
    "integration_preview": "Integration preview", "integrating": "Integrating", "integrated": "Integrated",
    "interrupted": "Execution interrupted",
}
STAGE_LABELS["committed"] = "Ready to integrate"
BUSY = frozenset({"analyzing", "planning", "coding", "reviewing", "executing", "testing", "reviewing_diff",
                  "integrating"})

# Ordered: the first matching fragment decides the user-facing message.
_FRIENDLY = (
    (("changed after the approval", "changed after approval", "proposal changed", "payload changed",
      "task changed after"), "Proposal changed after approval — approval required again."),
    (("differ from the approved", "differs from the approved"), "Actual diff does not match approved proposal."),
    (("changed since approval", "identity changed", "stale"),
     "The project changed after approval — review the new state and approve again."),
    (("is protected", "protected path"), "Protected path requested — task blocked."),
    (("outside the approved plan", "not in the plan", "unexpected file"),
     "The change touched files outside the approved plan — task blocked."),
    (("apply failed",), "The proposal could not be applied in the isolated worktree — the project is unchanged."),
    (("tests failed", "test failed", "no test ran", "covering the changed code failed"),
     "Tests failed — no commit allowed."),
    (("already used", "is used", "revoked"), "This approval was already used — a new approval is required."),
    (("no coding model", "not configured", "choose a main model"),
     "No coding model is configured — choose a main model or Models by workload in Settings."),
)


def friendly_error(text: str) -> str:
    message = " ".join(str(text or "").split())
    lowered = message.lower()
    for fragments, friendly in _FRIENDLY:
        if any(f in lowered for f in fragments):
            return f"{friendly} ({message[:300]})" if message and friendly not in message else friendly
    return message[:500]


def _clip(text: str, limit: int) -> tuple[str, bool]:
    text = text or ""
    return (text, False) if len(text) <= limit else (text[:limit], True)


def _impact(report) -> dict[str, Any] | None:
    if report is None:
        return None
    return {"risk": report.risk.value, "reasons": [r.reason for r in report.reasons],
            "reverse_dependencies": len(report.reverse_dependencies), "affected_tests": list(report.affected_tests),
            "callers": list(report.callers), "config": list(report.affected_config)}


def _plan(record) -> dict[str, Any] | None:
    planning = record.session.planning if record.session else None
    plan = planning.plan if planning else None
    if plan is None:
        return None
    return {
        "summary": plan.summary, "steps": list(plan.steps), "files_to_change": list(plan.files_to_change),
        "new_files": list(plan.new_files), "symbols": list(plan.symbols_to_change),
        "files_untouched": list(plan.files_untouched), "protected_paths": list(record.task.constraints.protected_paths),
        "risk": plan.risk.value, "impact": _impact(plan.impact),
        "checks": [{"kind": c.kind.value, "description": c.description, "targets": list(c.targets)}
                   for c in plan.test_plan.checks],
        "assumptions": list(plan.assumptions), "questions": list(plan.unresolved_questions),
    }


def _approval(record) -> dict[str, Any] | None:
    pending = record.session.pending if record.session else None
    if pending is None or record.stage.value != "awaiting_approval":
        return None
    proposal = pending.change.proposal
    diff, truncated = _clip(pending.preview_diff, MAX_DIFF_CHARS)
    binding = pending.binding
    return {
        "approval_id": pending.approval_id, "fingerprint": pending.fingerprint,
        "fingerprint_short": pending.fingerprint[:16],
        "strategy": proposal.strategy.strategy.value, "strategy_reason": proposal.strategy.reason,
        "target_files": list(binding.targets), "changes": list(proposal.change_descriptions),
        "proposed_diff": diff, "proposed_diff_truncated": truncated,
        "worktree_target": {"repo_root": binding.repo_root, "branch": binding.branch,
                            "base_commit": binding.base_commit,
                            "location": "new isolated worktree under .worktrees/ (parent checkout untouched)"},
        "review_rationale": pending.change.review.rationale,
    }


def _finding(f) -> dict[str, Any]:
    return {"category": f.category.value, "severity": f.severity.value, "message": f.message, "path": f.path}


def _execution(record) -> dict[str, Any] | None:
    attempts = record.session.attempts if record.session else []
    if not attempts:
        return None
    last = attempts[-1]
    result = last.result
    diff, truncated = _clip(result.diff, MAX_DIFF_CHARS)
    return {
        "attempt": last.number, "approval_id": last.approval_id, "fingerprint": last.fingerprint,
        "status": result.status, "reasons": [friendly_error(r) for r in result.reasons],
        "files_changed": list(result.files_changed), "additions": result.additions, "deletions": result.deletions,
        "actual_diff": diff, "actual_diff_truncated": truncated,
        "tests": [{"check": e.check.description, "kind": e.check.kind.value, "status": e.result.status.value,
                   "output": e.result.output[-MAX_OUTPUT_CHARS:], "seconds": e.seconds} for e in result.checks],
        "reviewer": {"verdict": last.review.status.value, "rationale": last.review.rationale,
                     "confidence": last.review.confidence,
                     "findings": [_finding(f) for f in last.review.findings],
                     "repair_instructions": list(last.review.repair_instructions)},
        "impact": _impact(last.impact),
        "worktree": {"path": result.worktree_path, "branch": result.worktree_branch,
                     "base_commit": result.base_commit, "state": dict(result.worktree_state)},
        "commit_status": result.commit_status,
    }


def _commit(record) -> dict[str, Any] | None:
    plan = record.commit_plan
    if plan is None and not record.commit_hash:
        return None
    view: dict[str, Any] = {"hash": record.commit_hash}
    if plan is not None:
        view.update({"files": list(plan.files), "stat": plan.stat, "additions": plan.additions,
                     "deletions": plan.deletions, "branch": plan.branch, "worktree_path": plan.worktree_path,
                     "base_commit": plan.base_commit, "parent_branch": plan.parent_branch,
                     "suggested_message": plan.suggested_message, "token": plan.token,
                     "note": "Commits only to the worktree branch. No push, no merge."})
    return view


def _actions(record) -> dict[str, bool]:
    stage = record.stage.value
    live_approval = stage == "awaiting_approval" and not record.restored
    can_repair = bool(record.session and record.session.can_repair) and stage == "awaiting_keep_reject"
    pr_status = (record.pr or {}).get("status")
    return {
        "approve": live_approval, "reject_proposal": live_approval,
        "keep": stage == "awaiting_keep_reject" and record.result is not None, "repair": can_repair,
        "reject": stage in ("awaiting_keep_reject", "kept", "ready_to_commit", "blocked", "failed", "committed",
                            "integration_preview", "integrated", "interrupted")
        or (stage == "awaiting_approval" and record.restored),
        "commit_prepare": stage == "ready_to_commit",
        "commit_confirm": stage == "ready_to_commit" and record.commit_plan is not None,
        "integration_preview": stage in ("committed", "integration_preview"),
        "integration_approve": stage == "integration_preview" and record.integration_preview is not None
        and record.integration_preview.status.value in ("clean", "needs_rebase_or_replay"),
        "integration_cancel": stage == "integration_preview",
        "pr_prepare": stage == "integrated",
        "pr_edit": stage == "integrated" and pr_status in ("draft", "approved_for_later"),
        **_remote_actions(record),
    }


REMOTE_LABELS = {
    "unavailable": "No remote configured", "not_checked": "Remote not checked", "ready_to_push": "Ready to push",
    "push_preview": "Push approval required", "pushed": "Pushed", "pr_ready": "PR ready to create",
    "pr_preview": "PR approval required", "pr_open": "PR open", "checks_running": "Checks running",
    "changes_requested": "Changes requested", "approved": "Approved", "merge_preview": "Merge approval required",
    "merged": "Merged", "blocked": "Blocked",
}


def remote_state(record) -> str:
    remote = record.remote or {}
    pending = remote.get("pending") or {}
    status = remote.get("pr_status") or {}
    info = remote.get("info")
    if remote.get("merged"):
        return "merged"
    if remote.get("blocked"):
        return "blocked"
    if remote.get("pr"):
        if "merge" in pending:
            return "merge_preview"
        if status.get("checks", {}).get("state") in ("pending",):
            return "checks_running"
        if status.get("reviews", {}).get("changes_requested"):
            return "changes_requested"
        if status.get("reviews", {}).get("approvals"):
            return "approved"
        return "pr_open"
    if remote.get("pushed"):
        return "pr_preview" if "pr" in pending else "pr_ready"
    if info is None:
        return "not_checked"
    if not info.get("available"):
        return "unavailable"
    return "push_preview" if "push" in pending else "ready_to_push"


def _remote_actions(record) -> dict[str, bool]:
    remote = record.remote or {}
    pending = remote.get("pending") or {}
    integrated = record.stage.value == "integrated" and (record.integration.get("review") or {}).get("verdict") == "pass"
    available = bool((remote.get("info") or {}).get("available"))
    ready = integrated and available and not remote.get("merged")
    return {
        "remote_detect": integrated,
        "push": ready and not remote.get("pushed"),
        "push_approve": integrated and "push" in pending and pending["push"].status == "ready",
        "create_remote_pr": ready and bool(remote.get("pushed")) and not remote.get("pr"),
        "pr_create_approve": integrated and "pr" in pending,
        "pr_refresh": bool(remote.get("pr")),
        "merge": ready and bool(remote.get("pr")),
        "merge_approve": integrated and "merge" in pending and pending["merge"].status == "clean",
        "repair_from_feedback": bool(remote.get("pr")) and not remote.get("merged"),
    }


def _remote(record) -> dict[str, Any] | None:
    remote = record.remote
    if not remote and record.stage.value != "integrated":
        return None
    remote = remote or {}
    state = remote_state(record)
    keys = ("info", "push_preview", "pushed", "pr_preview", "pr", "pr_status", "merge_preview", "merged", "blocked")
    view: dict[str, Any] = {k: remote[k] for k in keys if remote.get(k)}
    view.update({"state": state, "state_label": REMOTE_LABELS.get(state, state),
                 "pending": sorted((remote.get("pending") or {}).keys()), "events": list(remote.get("events") or [])[-30:]})
    return view


def _result(record) -> dict[str, Any] | None:
    result = record.result
    if result is None:
        return None
    return {"states": list(result.states), "target_branch": result.target_branch, "base_commit": result.base_commit,
            "worktree_branch": result.worktree_branch, "worktree_path": result.worktree_path,
            "result_commit": result.result_commit, "changed_files": list(result.changed_files),
            "additions": result.additions, "deletions": result.deletions, "tests": list(result.tests),
            "reviewer_verdict": result.reviewer_verdict, "reviewer_rationale": result.reviewer_rationale,
            "approval_source": result.approval_source, "proposal_fingerprint": result.proposal_fingerprint}


def _integration(record) -> dict[str, Any] | None:
    if not record.integration:
        return None
    view = dict(record.integration)
    preview = record.integration_preview
    if preview is not None and record.stage.value == "integration_preview":
        view["token"] = preview.token  # the approval names this exact preview
    if record.integration_final_diff:
        diff, truncated = _clip(record.integration_final_diff, MAX_DIFF_CHARS)
        view["final_diff"], view["final_diff_truncated"] = diff, truncated
    return view


def snapshot(record) -> dict[str, Any]:
    stage = record.stage.value
    return {
        "task_id": record.task_id, "description": record.task.description, "project": record.project_root,
        "stage": stage, "stage_label": STAGE_LABELS.get(stage, stage), "error": record.error,
        "busy": stage in BUSY, "restored": record.restored, "actions": _actions(record),
        "models": dict(record.audit.models), "route_source": record.audit.route_source,
        "routing": dict(record.audit.routing), "created_at": record.audit.created_at,
        "plan": _plan(record), "approval": _approval(record), "execution": _execution(record),
        "result": _result(record), "integration": _integration(record), "pr": dict(record.pr) if record.pr else None,
        "remote": _remote(record),
        "decisions": [{k: d.get(k) for k in ("decision", "source", "device", "at")} for d in record.audit.decisions],
        "attempts": [{"number": a.number, "approval_id": a.approval_id, "verdict": a.review.status.value,
                      "status": a.result.status} for a in (record.session.attempts if record.session else [])],
        "commit": _commit(record), "cleanup": dict(record.cleanup),
        "history": list(record.history), "timings": dict(record.timings),
    }
