"""CodingOrchestrator: Repository Intelligence → Architect → Coder ⇄ Reviewer → approval.

The orchestrator coordinates and never edits. It prepares the task context ONCE from a
(cached) RepositoryIntelligence instance, so every stage and every repair attempt reads
the same context without rescanning. Its successful end state is
``AWAITING_APPROVAL`` with an :class:`ApprovalRequest`; applying the change belongs to
MEU's safe execution layer after an explicit approval (``meu_coding.safe_execution``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from meu_coding.architect import Architect, PlanningError
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import (
    CheckResult,
    CodeChangeProposal,
    CodingTask,
    ImpactReport,
    ImplementationPlan,
    RepairRequest,
    ReviewRequest,
    ReviewResult,
    ReviewStatus,
    StageLog,
    TaskContext,
)
from meu_coding.safe_execution import ApprovalRequest
from meu_coding.impact import ImpactAnalyzer
from meu_coding.intelligence import RepositoryIntelligence
from meu_coding.repair_loop import DEFAULT_MAX_REPAIRS, Attempt, RepairLoop, RepairOutcome
from meu_coding.reviewer import Reviewer


class OutcomeStatus(str, Enum):
    PLANNING_FAILED = "planning_failed"
    BLOCKED = "blocked"
    NEEDS_FIX = "needs_fix"  # repairs exhausted or stalled; nothing to approve
    AWAITING_APPROVAL = "awaiting_approval"


@dataclass(frozen=True)
class CodingResult:
    task: CodingTask
    status: OutcomeStatus
    stages: tuple[str, ...]
    plan: ImplementationPlan | None = None
    plan_errors: tuple[str, ...] = ()
    repair: RepairOutcome | None = None
    impact: ImpactReport | None = None
    approval: ApprovalRequest | None = None
    context: TaskContext | None = None  # the shared context every stage used

    @property
    def attempts(self) -> tuple[Attempt, ...]:
        return self.repair.attempts if self.repair else ()

    @property
    def proposal(self) -> CodeChangeProposal | None:
        return self.repair.final.proposal if self.repair else None

    @property
    def review(self) -> ReviewResult | None:
        return self.repair.final.review if self.repair else None


def context_query(task: CodingTask) -> str:
    return " ".join((task.description, *task.explicit_files)).strip()


def prepare_context(intelligence: RepositoryIntelligence, task: CodingTask, budget: int) -> TaskContext:
    """One context query against the cached index; no scan unless nothing is indexed yet."""
    query = context_query(task)
    bundle, ranked = intelligence.context_with_ranking(query, budget, tuple(task.context_hints))
    graph = intelligence.graph
    files_by_path = intelligence.analysis.files_by_path
    focus = tuple(dict.fromkeys((*task.explicit_files, *(i.path for i in bundle.items), *(r.path for r in ranked))))
    present = [p for p in focus if p in files_by_path]
    return TaskContext(
        task=task, bundle=bundle, ranked=ranked,
        dependencies={p: graph.get_dependencies(p) for p in present},
        reverse_dependencies={p: graph.get_reverse_dependencies(p) for p in present},
        known_paths=frozenset(files_by_path),
        file_bytes={p: files_by_path[p].size for p in present},
    )


class CodingOrchestrator:
    def __init__(self, intelligence: RepositoryIntelligence, coder: Coder,
                 reviewer: Reviewer | None = None, architect: Architect | None = None,
                 max_repairs: int = DEFAULT_MAX_REPAIRS, context_budget: int = 12_000) -> None:
        reviewer = reviewer or Reviewer()
        if reviewer.model is not None and reviewer.model is coder.model:
            raise ValueError("the Reviewer must not share the Coder's model instance")
        self.intelligence = intelligence
        self.coder = coder
        self.reviewer = reviewer
        self._architect = architect
        self.loop = RepairLoop(max_repairs)
        self.context_budget = context_budget

    @property
    def impact(self) -> ImpactAnalyzer:
        return ImpactAnalyzer(self.intelligence.graph)

    def run(self, task: CodingTask, *, refresh_paths: Iterable[str] | None = None,
            check_results: tuple[CheckResult, ...] = ()) -> CodingResult:
        """``refresh_paths``: files known to have changed since the index was built; only
        those are re-read. ``check_results``: results the safe layer already produced."""
        log = StageLog()
        if refresh_paths is not None:
            changed = self.intelligence.refresh_changed_files(refresh_paths)
            log.add("refresh", f"{len(changed.changed)} file(s)")
        context = prepare_context(self.intelligence, task, self.context_budget)
        log.add("context", f"{len(context.bundle.items)} item(s), {context.bundle.size} chars")
        impact = self.impact
        architect = self._architect or Architect(impact)
        try:
            plan = architect.plan(context)
        except PlanningError as exc:
            log.add("architect", "failed")
            return CodingResult(task, OutcomeStatus.PLANNING_FAILED, log.stages, plan_errors=exc.errors or (str(exc),),
                                context=context)
        log.add("architect", f"{len(plan.files_to_change) + len(plan.new_files)} file(s), risk {plan.risk.value}")

        def propose(repair: RepairRequest | None) -> CodeChangeProposal:
            log.add("coder" if repair is None else "repair", f"attempt {repair.attempt if repair else 0}")
            return self.coder.propose(task, plan, context, repair)

        def review(proposal: CodeChangeProposal) -> ReviewResult:
            result = self.reviewer.review(ReviewRequest(task, plan, proposal, context, task.recent_diff,
                                                        check_results))
            log.add("reviewer", result.status.value)
            return result

        outcome = self.loop.run(propose, review)
        final_impact = impact.analyze(outcome.final.proposal.affected_files, plan.symbols_to_change)
        if outcome.status == ReviewStatus.BLOCK:
            status, approval = OutcomeStatus.BLOCKED, None
        elif outcome.status == ReviewStatus.FIX:
            status, approval = OutcomeStatus.NEEDS_FIX, None
        else:
            status = OutcomeStatus.AWAITING_APPROVAL
            approval = ApprovalRequest.for_review(plan, outcome.final.proposal, outcome.final.review)
            log.add("approval_boundary", approval.fingerprint[:12])
        return CodingResult(task, status, log.stages, plan, (), outcome, final_impact, approval, context)
