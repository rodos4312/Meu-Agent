"""The durable representation of an executed coding result.

Everything after execution (keep, reject, commit, integration, PR preview, recovery after a
restart) works from this record, not from in-memory engine objects, so a restarted backend
can continue a result only through explicit user actions. States are appended explicitly by
the operation that earned them; nothing is inferred.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ResultState(str, Enum):
    EXECUTED = "executed"
    TESTED = "tested"
    REVIEWER_PASS = "reviewer_pass"
    KEPT = "kept"
    COMMITTED_IN_WORKTREE = "committed_in_worktree"
    READY_TO_INTEGRATE = "ready_to_integrate"
    INTEGRATED = "integrated"
    REJECTED = "rejected"
    BLOCKED = "blocked"


@dataclass
class ResultRecord:
    task_id: str
    repo_root: str
    target_branch: str
    base_commit: str
    worktree_path: str
    worktree_branch: str
    proposal_fingerprint: str
    approval_fingerprint: str
    approval_source: str
    changed_files: list[str]
    additions: int
    deletions: int
    tests: list[dict[str, str]]
    planned_checks: list[dict[str, Any]]
    reviewer_verdict: str
    reviewer_rationale: str
    reviewed_diff_digest: str
    states: list[str] = field(default_factory=list)
    result_commit: str = ""

    def advance(self, state: ResultState) -> None:
        if state.value not in self.states:
            self.states.append(state.value)

    def has(self, state: ResultState) -> bool:
        return state.value in self.states

    @property
    def tests_passed(self) -> bool:
        ran = [t for t in self.tests if t.get("status") in ("passed", "failed")]
        return bool(ran) and all(t.get("status") == "passed" for t in ran)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ResultRecord | None:
        if not isinstance(data, dict) or not data.get("task_id"):
            return None
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        try:
            return cls(**known)
        except TypeError:
            return None


def result_from_attempt(task_id: str, attempt, request, approval_source: str) -> ResultRecord:
    """Build the record from a Phase 3/4 execution attempt (``ExecutionAttempt``)."""
    from meu_coding.commit_flow import diff_digest

    result = attempt.result
    binding = request.binding
    record = ResultRecord(
        task_id=task_id, repo_root=binding.repo_root, target_branch=binding.branch, base_commit=binding.base_commit,
        worktree_path=result.worktree_path, worktree_branch=result.worktree_branch,
        proposal_fingerprint=binding.proposal_fingerprint, approval_fingerprint=request.fingerprint,
        approval_source=approval_source, changed_files=list(result.files_changed), additions=result.additions,
        deletions=result.deletions,
        tests=[{"check": e.check.description, "kind": e.check.kind.value, "status": e.result.status.value}
               for e in result.checks],
        planned_checks=[{"kind": c.kind.value, "description": c.description, "targets": list(c.targets)}
                        for c in request.change.plan.test_plan.checks],
        reviewer_verdict=attempt.review.status.value, reviewer_rationale=attempt.review.rationale[:500],
        reviewed_diff_digest=diff_digest(result.diff, tuple(sorted(result.files_changed))),
    )
    if result.executed:
        record.advance(ResultState.EXECUTED)
        if result.checks:
            record.advance(ResultState.TESTED)
        if attempt.review.status.value == "pass":
            record.advance(ResultState.REVIEWER_PASS)
    else:
        record.advance(ResultState.BLOCKED)
    return record
