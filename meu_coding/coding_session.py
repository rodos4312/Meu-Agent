"""CodingSession: plan → propose → review → APPROVAL → isolated execution → checks → actual-diff
review, with bounded repairs that each need a NEW approval.

Final states stop before any commit: the user (or MEU) decides what happens to the worktree.

    PLANNING_FAILED / BLOCKED / NEEDS_FIX   (Phase 2 outcomes; nothing to approve)
    AWAITING_APPROVAL                       an ExecutionApprovalRequest is pending
    REVIEWED                                executed in a worktree, tested, reviewed: PASS/FIX/BLOCK
    AWAITING_APPROVAL (repair n)            a repair proposal passed review; the old approval is revoked

The same RepositoryIntelligence instance and the same prepared TaskContext serve every
stage and attempt; after execution only the changed worktree files are re-extracted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum

from meu_coding.architect import Architect
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    ImpactReport,
    CodingTask,
    RepairRequest,
    ReviewRequest,
    ReviewResult,
    ReviewStatus,
    TaskContext,
)
from meu_coding.execution_review import impact_of, refresh_changed, review_execution
from meu_coding.intelligence import RepositoryIntelligence
from meu_coding.orchestrator import CodingOrchestrator, CodingResult, OutcomeStatus
from meu_coding.repair_loop import DEFAULT_MAX_REPAIRS, Attempt, RepairOutcome
from meu_coding.reviewer import Reviewer
from meu_coding.safe_execution import (
    ApprovalError,
    ApprovalRequest,
    ExecutionApprovalRequest,
    ExecutionBlocked,
    ExecutionDecision,
    ExecutionResult,
    SafeExecutionAdapter,
    approve_execution,
)


class SessionState(str, Enum):
    PLANNING_FAILED = "planning_failed"
    BLOCKED = "blocked"
    NEEDS_FIX = "needs_fix"
    AWAITING_APPROVAL = "awaiting_approval"
    REVIEWED = "reviewed"


@dataclass(frozen=True)
class ExecutionAttempt:
    number: int
    approval_id: str
    fingerprint: str
    result: ExecutionResult
    review: ReviewResult
    timings: dict[str, float]
    impact: ImpactReport | None = None


@dataclass
class CodingSession:
    intelligence: RepositoryIntelligence
    coder: Coder
    reviewer: Reviewer = field(default_factory=Reviewer)
    architect: Architect | None = None
    adapter: SafeExecutionAdapter = field(default_factory=SafeExecutionAdapter)
    max_repairs: int = DEFAULT_MAX_REPAIRS
    context_budget: int = 12_000
    state: SessionState | None = None
    stages: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    attempts: list[ExecutionAttempt] = field(default_factory=list)
    planning: CodingResult | None = None
    pending: ExecutionApprovalRequest | None = None
    last_request: ExecutionApprovalRequest | None = None  # the request the last execution consumed
    context: TaskContext | None = None
    blocked_reason: str = ""

    # ── plan, propose, pre-review ───────────────────────────────────────────

    def start(self, task: CodingTask) -> SessionState:
        started = time.perf_counter()
        orchestrator = CodingOrchestrator(self.intelligence, self.coder, self.reviewer, self.architect,
                                          self.max_repairs, self.context_budget)
        self.planning = orchestrator.run(task)
        self.timings["plan_propose_review"] = round(time.perf_counter() - started, 3)
        self.stages.extend(self.planning.stages)
        self.context = self.planning.context
        if self.planning.status != OutcomeStatus.AWAITING_APPROVAL:
            self.state = SessionState(self.planning.status.value)
            return self.state
        return self._offer(task, self.planning.approval)

    def _offer(self, task: CodingTask, change: ApprovalRequest) -> SessionState:
        try:
            self.pending = self.adapter.prepare(task, change, self.intelligence.root)
        except ExecutionBlocked as exc:
            self.pending, self.state, self.blocked_reason = None, SessionState.BLOCKED, str(exc)
            self.stages.append("approval_refused")
            return self.state
        self.stages.append("awaiting_approval")
        self.state = SessionState.AWAITING_APPROVAL
        return self.state

    # ── approval and execution ──────────────────────────────────────────────

    def execute(self, decision: ExecutionDecision) -> ExecutionAttempt:
        if self.state != SessionState.AWAITING_APPROVAL or self.pending is None:
            raise ApprovalError("nothing is awaiting approval")
        if decision.approval_id != self.pending.approval_id:
            raise ApprovalError("the decision is not for the current approval")
        request = self.pending
        approved = approve_execution(request, decision)  # raises on any mismatch
        self.pending = None
        self.last_request = request
        self.stages.append("approved")
        result = self.adapter.execute(approved, request.change.plan.test_plan.checks)
        self.stages += ["executed", "tested"] if result.executed else [f"execution_{result.status}"]
        mark = time.perf_counter()
        overlay = refresh_changed(self.intelligence, result.worktree_path, result.files_changed) \
            if result.executed else None
        refresh_seconds = time.perf_counter() - mark
        mark = time.perf_counter()
        impact = impact_of(self.intelligence, result, request)
        review = review_execution(request, result, self.context, self.reviewer, overlay or _EMPTY_OVERLAY, impact)
        timings = {**result.timings, "targeted_refresh": round(refresh_seconds, 4),
                   "actual_review": round(time.perf_counter() - mark, 3)}
        self.stages.append(f"reviewed_{review.status.value}")
        attempt = ExecutionAttempt(len(self.attempts), request.approval_id, request.fingerprint, result,
                                   review, timings, impact)
        self.attempts.append(attempt)
        self.state = SessionState.REVIEWED
        return attempt

    # ── repair: a new proposal, a new review, a NEW approval ────────────────

    @property
    def can_repair(self) -> bool:
        last = self.attempts[-1] if self.attempts else None
        return (self.state == SessionState.REVIEWED and last is not None
                and last.review.status == ReviewStatus.FIX and bool(last.review.repair_instructions)
                and len(self.attempts) <= self.max_repairs)

    def repair(self) -> SessionState:
        if not self.can_repair:
            raise ApprovalError("no repair is allowed now")
        last = self.attempts[-1]
        task, plan = self.planning.task, self.planning.plan
        previous = self.planning.proposal  # the proposal that was approved and executed last
        if self.pending is not None:
            self.adapter.revoke(self.pending.approval_id)
        self.stages.append(f"repair_{len(self.attempts)}")
        started = time.perf_counter()
        repair = RepairRequest(len(self.attempts), previous, last.review)
        proposal = self.coder.propose(task, plan, self.context, repair)
        pre = self.reviewer.review(ReviewRequest(task, plan, proposal, self.context, task.recent_diff))
        self.timings[f"repair_{len(self.attempts)}"] = round(time.perf_counter() - started, 3)
        self.stages.append(f"reviewer_{pre.status.value}")
        if pre.status != ReviewStatus.PASS:
            self.state = SessionState.BLOCKED if pre.status == ReviewStatus.BLOCK else SessionState.NEEDS_FIX
            return self.state
        self.planning = _with_proposal(self.planning, proposal, pre)
        return self._offer(task, ApprovalRequest.for_review(plan, proposal, pre))


@dataclass(frozen=True)
class _Overlay:
    extractions: dict
    seconds: float = 0.0


_EMPTY_OVERLAY = _Overlay({})


def _with_proposal(result: CodingResult, proposal: CodeChangeProposal, review: ReviewResult) -> CodingResult:
    attempts = (*result.attempts, Attempt(len(result.attempts), proposal, review))
    return replace(result, repair=RepairOutcome(attempts, "repair after execution review"))
