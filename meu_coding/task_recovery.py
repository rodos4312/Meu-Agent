"""Rebuilding coding tasks from their audit records after a restart.

A restored task never resumes anything. Each stored stage maps to an explicit recovered
stage: a pending approval EXPIRES (its in-memory approval object is gone, so nothing can
approve it), an interrupted mutating step becomes INTERRUPTED (only Reject, which follows the
existing worktree cleanup rules), and settled results (awaiting keep/reject, ready to commit,
committed in the worktree, integrated) come back with their durable ``ResultRecord`` so the
user can continue through the same explicit, re-verified actions.
"""

from __future__ import annotations

from meu_coding.coding_interfaces import CodingTask
from meu_coding.coding_result import ResultRecord

EXPIRED = "The approval expired when Meu restarted — reject it and start the task again."
INTERRUPTED = ("Meu restarted during this step; nothing resumed automatically. The worktree is preserved "
               "for inspection — reject the task to clean it up through the safe cleanup rules.")
PLANNING_LOST = "Meu restarted while planning; nothing was executed. Start the task again."
PREVIEW_DROPPED = "The integration preview was discarded by a restart — preview the integration again."

_INTERRUPTED = {"executing", "testing", "reviewing_diff", "integrating"}
_PLANNING = {"analyzing", "planning", "coding", "reviewing"}


def recovered_stage(stored: str) -> tuple[str, str]:
    """``(stage, message)`` a restored task starts in."""
    if stored == "awaiting_approval":
        return "awaiting_approval", EXPIRED
    if stored in _INTERRUPTED:
        return "interrupted", INTERRUPTED
    if stored in _PLANNING:
        return "failed", PLANNING_LOST
    if stored == "integration_preview":
        return "committed", PREVIEW_DROPPED
    return stored, ""


def restore_record(audit, record_type, stage_type):
    stored = audit.stages[-1]["stage"] if audit.stages else "failed"
    stage_name, message = recovered_stage(stored)
    try:
        stage = stage_type(stage_name)
    except ValueError:
        stage, message = stage_type("failed"), INTERRUPTED
    record = record_type(audit.task_id, audit.project, CodingTask(audit.description or "(restored task)"), audit,
                         stage=stage, restored=True, history=[s["stage"] for s in audit.stages])
    record.result = ResultRecord.from_dict(audit.result)
    record.integration = dict(audit.integration or {})
    record.integration.pop("token", None)
    record.commit_hash = audit.commit_hash
    record.pr = dict(audit.pr) if audit.pr else None
    record.remote = {**audit.remote, "events": list(audit.remote.get("events") or [])} if audit.remote else None
    record.error = message or audit.error
    return record
