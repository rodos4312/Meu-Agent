"""Reviewer: an independent PASS / FIX / BLOCK verdict on a proposal.

The verdict comes from deterministic rules over the task, the plan, the proposal's
operations and any check results; it never reads the Coder's own assumptions or notes to
decide. An optional ``ReviewModel`` adds findings, and the most severe finding wins, so a
model cannot turn a rule's FIX or BLOCK into a PASS. Passing tests do not imply PASS:
every rule runs whether or not results are present.
"""

from __future__ import annotations

from collections.abc import Callable

from meu_coding.checks import static_syntax_errors
from meu_coding.coding_interfaces import (
    CheckKind,
    CheckStatus,
    EditAction,
    EditStrategy,
    FindingCategory,
    ReviewFinding,
    ReviewModel,
    ReviewRequest,
    ReviewResult,
    ReviewStatus,
    RiskLevel,
)
from meu_coding.relevance import is_test_path
from meu_coding.scope import is_protected, is_security_path, path_problem

C = FindingCategory
_SEVERITY = {ReviewStatus.PASS: 0, ReviewStatus.FIX: 1, ReviewStatus.BLOCK: 2}


def _finding(category, severity, message, path=None, repair=None) -> ReviewFinding:
    return ReviewFinding(category, severity, message, path, repair)


def _check_empty(r: ReviewRequest) -> list[ReviewFinding]:
    if r.proposal.operations:
        return []
    return [_finding(C.MISSING_REQUIREMENT, ReviewStatus.FIX, "the proposal contains no edits",
                     repair="propose the edits the plan describes")]


def _check_format(r: ReviewRequest) -> list[ReviewFinding]:
    return [_finding(C.CORRECTNESS, ReviewStatus.FIX, e, repair=f"fix the edit payload: {e}")
            for e in r.proposal.format_errors]


def _check_paths(r: ReviewRequest) -> list[ReviewFinding]:
    out = []
    constraints = r.task.constraints
    allowed = r.plan.allowed_paths
    untouched = set(r.plan.files_untouched)
    for path in r.proposal.affected_files:
        problem = path_problem(path)
        if problem:
            out.append(_finding(C.SCOPE_VIOLATION, ReviewStatus.BLOCK, problem, path))
        elif is_protected(path, constraints.protected_paths):
            out.append(_finding(C.SCOPE_VIOLATION, ReviewStatus.BLOCK, f"{path} is protected", path))
        elif path in untouched:
            out.append(_finding(C.UNEXPECTED_FILE, ReviewStatus.FIX, f"the plan keeps {path} untouched", path,
                                repair=f"do not edit {path}; keep the change inside the planned files"))
        elif path not in allowed:
            out.append(_finding(C.UNEXPECTED_FILE, ReviewStatus.FIX, f"{path} is not in the plan", path,
                                repair=f"remove the edit to {path} or keep the change inside the planned files"))
    if len(r.proposal.affected_files) > constraints.max_files:
        out.append(_finding(C.SCOPE_VIOLATION, ReviewStatus.BLOCK,
                            f"touches {len(r.proposal.affected_files)} files; the limit is {constraints.max_files}"))
    return out


def _check_actions(r: ReviewRequest) -> list[ReviewFinding]:
    out = []
    constraints = r.task.constraints
    for op in r.proposal.operations:
        exists = r.context.exists(op.path)
        if op.action == EditAction.DELETE and not constraints.allow_deletes:
            out.append(_finding(C.SCOPE_VIOLATION, ReviewStatus.BLOCK, f"deletes {op.path}; deletes are not allowed",
                                op.path))
        elif op.action == EditAction.CREATE and not constraints.allow_new_files:
            out.append(_finding(C.SCOPE_VIOLATION, ReviewStatus.BLOCK,
                                f"creates {op.path}; new files are not allowed", op.path))
        elif op.action == EditAction.CREATE and exists:
            out.append(_finding(C.CORRECTNESS, ReviewStatus.FIX, f"creates {op.path}, which already exists",
                                op.path, repair=f"edit {op.path} in place instead of creating it"))
        elif op.action != EditAction.CREATE and not exists:
            out.append(_finding(C.CORRECTNESS, ReviewStatus.FIX, f"{op.action.value}s {op.path}, which does not exist",
                                op.path, repair=f"create {op.path} as a new file or edit an existing file"))
    return out


def _payload_text(r: ReviewRequest) -> str:
    return "\n".join(p for op in r.proposal.operations
                     for p in (op.search, op.replace, op.content, op.patch) if p)


def _check_missing(r: ReviewRequest) -> list[ReviewFinding]:
    touched = set(r.proposal.affected_files)
    out = [_finding(C.MISSING_REQUIREMENT, ReviewStatus.FIX, f"the plan changes {p}, the proposal does not", p,
                    repair=f"make the planned change in {p}")
           for p in (*r.plan.files_to_change, *r.plan.new_files) if p not in touched]
    # A body edit need not repeat the symbol's name, so a symbol counts as addressed when an
    # edit touches a file the ranking matched it in, or when an edit names it.
    text = _payload_text(r)
    in_touched = {s for item in r.context.ranked if item.path in touched for s in item.symbols}
    for name in r.plan.symbols_to_change:
        if name not in in_touched and name.rsplit(".", 1)[-1] not in text:
            out.append(_finding(C.MISSING_REQUIREMENT, ReviewStatus.FIX,
                                f"the plan changes {name}, no edit mentions it", repair=f"change {name} as planned"))
    return out


def _check_tests(r: ReviewRequest) -> list[ReviewFinding]:
    out = []
    unit = r.plan.test_plan.of_kind(CheckKind.UNIT_TEST)
    needs_new_test = any(c.required and not c.targets for c in unit)
    if needs_new_test and not any(is_test_path(p) for p in r.proposal.affected_files):
        out.append(_finding(C.TEST_GAP, ReviewStatus.FIX, "no test covers the changed behaviour",
                            repair="add a test for the changed behaviour"))
    results = {res.key: res for res in r.test_results}
    for check in r.plan.test_plan.checks:
        result = results.get(check.key)
        if result is not None and result.status == CheckStatus.FAILED:
            out.append(_finding(C.REGRESSION, ReviewStatus.FIX, f"{check.description} failed: {result.output[:300]}",
                                repair=f"make '{check.description}' pass"))
        elif check.required and (result is None or result.status == CheckStatus.NOT_RUN):
            out.append(_finding(C.TEST_GAP, ReviewStatus.PASS, f"not yet run: {check.description}"))
    return out


def _check_syntax(r: ReviewRequest) -> list[ReviewFinding]:
    return [_finding(C.CORRECTNESS, ReviewStatus.FIX, f"{path} does not parse: {message}", path,
                     repair=f"fix the syntax error in {path} ({message})")
            for path, message in static_syntax_errors(r.proposal)]


def _check_risk(r: ReviewRequest) -> list[ReviewFinding]:
    out = []
    for op in r.proposal.operations:
        if op.strategy == EditStrategy.WHOLE_FILE and op.action == EditAction.UPDATE:
            out.append(_finding(C.RISKY_CHANGE, ReviewStatus.PASS, f"rewrites all of {op.path}", op.path))
    for path in r.proposal.affected_files:
        if is_security_path(path):
            out.append(_finding(C.RISKY_CHANGE, ReviewStatus.PASS, f"security-sensitive file: {path}", path))
    if r.plan.risk == RiskLevel.HIGH and r.plan.impact is not None:
        out.append(_finding(C.REGRESSION, ReviewStatus.PASS, "high-risk change: " + "; ".join(
            reason.reason for reason in r.plan.impact.reasons if reason.level == RiskLevel.HIGH)))
    return out


RULES: tuple[Callable[[ReviewRequest], list[ReviewFinding]], ...] = (
    _check_empty, _check_format, _check_paths, _check_actions, _check_missing,
    _check_tests, _check_syntax, _check_risk,
)


class Reviewer:
    def __init__(self, model: ReviewModel | None = None) -> None:
        self.model = model

    def review(self, request: ReviewRequest) -> ReviewResult:
        findings = [f for rule in RULES for f in rule(request)]
        if self.model is not None:
            findings += list(self.model.review(request))
        return _verdict(findings, bool(request.test_results))


def _verdict(findings: list[ReviewFinding], has_results: bool) -> ReviewResult:
    worst = max((f.severity for f in findings), key=_SEVERITY.__getitem__, default=ReviewStatus.PASS)
    repairs = tuple(dict.fromkeys(f.repair or f.message for f in findings if f.severity == ReviewStatus.FIX))
    notes = [f for f in findings if f.severity == ReviewStatus.PASS]
    if worst == ReviewStatus.PASS:
        confidence = max(0.4, (0.9 if has_results else 0.7) - 0.05 * len(notes))
        rationale = "all review rules passed" + (f"; {len(notes)} note(s)" if notes else "")
    else:
        blocking = [f for f in findings if f.severity == worst]
        confidence = 0.9
        rationale = f"{worst.value}: " + "; ".join(f.message for f in blocking[:5])
    return ReviewResult(worst, tuple(findings), repairs if worst == ReviewStatus.FIX else (),
                        round(confidence, 2), rationale)
