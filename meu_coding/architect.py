"""Architect: turns a task and its prepared context into a validated ImplementationPlan.

The Architect only plans. It never writes, runs commands or commits. A deterministic
heuristic drafts the plan from the Phase 1 ranking and graph; an optional
``PlanningModel`` may refine that draft, and every plan, drafted or refined, passes the
same :func:`validate_plan` before anything downstream sees it.
"""

from __future__ import annotations

from dataclasses import replace

from meu_coding.checks import build_test_plan
from meu_coding.coding_interfaces import (
    CheckKind,
    CodingTask,
    ImpactReport,
    ImplementationPlan,
    PlanningModel,
    PlanningRequest,
    PlanValidation,
    TaskContext,
)
from meu_coding.impact import ImpactAnalyzer
from meu_coding.relevance import WEIGHTS, is_test_path, parse_query
from meu_coding.scope import is_config_path, is_protected, path_problem

STRONG_SCORE = WEIGHTS["exact_symbol"]


class PlanningError(Exception):
    """The Architect could not produce a usable plan; nothing downstream may run."""

    def __init__(self, message: str, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors


class Architect:
    def __init__(self, impact: ImpactAnalyzer, model: PlanningModel | None = None) -> None:
        self.impact = impact
        self.model = model

    def plan(self, context: TaskContext) -> ImplementationPlan:
        draft = draft_plan(context, self.impact)
        plan = draft
        if self.model is not None:
            plan = self.model.plan(PlanningRequest(context.task, context, draft))
            if plan.impact is None:  # the model may skip impact; recompute it from the graph
                impact = self.impact.analyze(plan.files_to_change + plan.new_files, plan.symbols_to_change)
                plan = _with_impact(plan, impact)
        validation = validate_plan(plan, context)
        if not validation.ok:
            raise PlanningError("plan failed validation", validation.errors)
        return plan


def _with_impact(plan: ImplementationPlan, impact: ImpactReport) -> ImplementationPlan:
    return replace(plan, impact=impact, risk=max(plan.risk, impact.risk, key=lambda r: r.rank))


def _choose_files(context: TaskContext) -> tuple[list[str], list[str], list[str]]:
    """``(existing files to change, new files, assumptions)``."""
    task = context.task
    protected = task.constraints.protected_paths
    explicit = [p for p in task.explicit_files if not is_protected(p, protected)]
    existing = [p for p in explicit if context.exists(p)]
    new = [p for p in explicit if not context.exists(p)]
    assumptions = []
    # Files the user named are never swapped for ranked guesses, even when all are protected.
    if not task.explicit_files:
        strong = [r.path for r in context.ranked
                  if r.score >= STRONG_SCORE and not is_test_path(r.path)
                  and not is_protected(r.path, protected)]
        existing = strong[: task.constraints.max_files]
        if not existing:
            weak = [r.path for r in context.ranked
                    if not is_test_path(r.path) and not is_protected(r.path, protected)]
            existing = weak[:1]
            if existing:
                assumptions.append(f"no strong match; assuming the change belongs in {existing[0]}")
    return existing, new, assumptions


def _symbols(context: TaskContext, files: list[str]) -> tuple[str, ...]:
    wanted = parse_query(context.task.description)
    names = wanted.strong_identifiers | wanted.weak_identifiers
    chosen = set(files)
    found = [s for r in context.ranked if r.path in chosen for s in r.symbols]
    found += [n for n in sorted(names) if any(n in r.symbols for r in context.ranked if r.path in chosen)]
    return tuple(dict.fromkeys(found))


def draft_plan(context: TaskContext, impact_analyzer: ImpactAnalyzer) -> ImplementationPlan:
    task = context.task
    files, new_files, assumptions = _choose_files(context)
    symbols = _symbols(context, files)
    impact = impact_analyzer.analyze(files + new_files, symbols)
    test_plan = build_test_plan(files + new_files, impact.affected_tests)
    context_only = [i.path for i in context.bundle.items if i.path not in files and i.path not in new_files]
    untouched = tuple(dict.fromkeys((*task.constraints.protected_paths, *context_only)))
    blocked = [p for p in task.explicit_files if is_protected(p, task.constraints.protected_paths)]
    questions = tuple(f"{p} is protected; may it change, or which file should change instead?" for p in blocked)
    if not files and not new_files and not questions:
        questions = ("No file in the repository matches this task; which file should change?",)
    steps = [f"Change {f}" + (f" ({', '.join(s for s in symbols)})" if symbols else "") for f in files]
    steps += [f"Create {f}" for f in new_files]
    if impact.affected_tests:
        steps.append("Keep these tests passing or update them: " + ", ".join(impact.affected_tests[:8]))
    elif test_plan.of_kind(CheckKind.UNIT_TEST):
        steps.append("Add a test that covers the changed behaviour")
    safety = ["Edits are proposals; they apply only after review and MEU approval."]
    if impact.risk.rank >= 2:
        safety.append("High risk: " + "; ".join(r.reason for r in impact.reasons if r.level == impact.risk))
    if task.recent_diff:
        assumptions.append("the recent diff is the starting point and is not reverted")
    return ImplementationPlan(
        summary=task.description.strip().splitlines()[0][:200] if task.description.strip() else "",
        files_to_change=tuple(files), symbols_to_change=symbols, files_untouched=untouched,
        steps=tuple(steps), test_plan=test_plan, risk=impact.risk, impact=impact,
        new_files=tuple(new_files), assumptions=tuple(assumptions),
        unresolved_questions=questions, safety_notes=tuple(safety),
    )


def _path_errors(plan: ImplementationPlan, task: CodingTask) -> list[str]:
    errors = []
    for path in (*plan.files_to_change, *plan.new_files):
        problem = path_problem(path)
        if problem:
            errors.append(problem)
        elif is_protected(path, task.constraints.protected_paths):
            errors.append(f"{path} is protected and cannot be planned for change")
    overlap = set(plan.files_to_change) & set(plan.files_untouched)
    if overlap:
        errors.append(f"files both changed and untouched: {sorted(overlap)}")
    return errors


def validate_plan(plan: ImplementationPlan, context: TaskContext) -> PlanValidation:
    task = context.task
    errors = _path_errors(plan, task)
    targets = (*plan.files_to_change, *plan.new_files)
    if not targets:
        errors.append("plan changes no file")
    if len(targets) > task.constraints.max_files:
        errors.append(f"plan changes {len(targets)} files; the limit is {task.constraints.max_files}")
    if plan.new_files and not task.constraints.allow_new_files:
        errors.append("plan creates files but the task does not allow new files")
    missing = [p for p in plan.files_to_change if not context.exists(p)]
    if missing:
        errors.append(f"planned files do not exist (list them as new files): {missing}")
    if not plan.steps:
        errors.append("plan has no implementation steps")
    changes_code = any(not is_test_path(p) and not is_config_path(p) for p in targets)
    if task.constraints.require_tests and changes_code and not plan.test_plan.of_kind(CheckKind.UNIT_TEST):
        errors.append("plan names no tests")
    if plan.unresolved_questions:
        errors.append("unresolved questions: " + " | ".join(plan.unresolved_questions))
    return PlanValidation(tuple(errors))
