"""Review of what execution ACTUALLY did: the real diff, the real check results, the
changed files re-indexed, not only the proposal that was approved.

Rules here are independent of the Coder and of the pre-execution review; the Phase 2
Reviewer (and its optional model) runs again with the actual diff and results, and the most
severe finding wins. Passing checks never excuse a scope or safety finding.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from meu_coding.coding_interfaces import (
    CheckStatus,
    FindingCategory,
    ImpactReport,
    ReviewFinding,
    ReviewRequest,
    ReviewResult,
    ReviewStatus,
    TaskContext,
)
from meu_coding.impact import ImpactAnalyzer
from meu_coding.intelligence import RepositoryIntelligence
from meu_coding.interfaces import ExtractionResult
from meu_coding.relevance import is_test_path
from meu_coding.repo_index import language_for
from meu_coding.reviewer import Reviewer, verdict
from meu_coding.safe_execution import ExecutionApprovalRequest, ExecutionResult
from meu_coding.scope import is_config_path

C = FindingCategory


@dataclass(frozen=True)
class OverlayRefresh:
    """Changed worktree files re-extracted with the Phase 1 extractor (deep); nothing else."""

    extractions: dict[str, ExtractionResult]
    seconds: float


def refresh_changed(intelligence: RepositoryIntelligence, worktree: str | Path,
                    files: tuple[str, ...]) -> OverlayRefresh:
    started = time.perf_counter()
    root = Path(worktree)
    out = {}
    for rel in files:
        language = language_for(rel)
        target = root / rel
        if language == "unknown" or not target.is_file():
            continue
        source = target.read_bytes().decode("utf-8", errors="replace")
        out[rel] = intelligence.extractor.extract(rel, source, language)
    return OverlayRefresh(out, round(time.perf_counter() - started, 4))


def _f(category, severity, message, path=None, repair=None) -> ReviewFinding:
    return ReviewFinding(category, severity, message, path, repair)


def _status_findings(result: ExecutionResult) -> list[ReviewFinding]:
    if result.status == "blocked":
        return [_f(C.SCOPE_VIOLATION, ReviewStatus.BLOCK, "execution blocked: " + "; ".join(result.reasons))]
    if result.status == "failed":
        return [_f(C.CORRECTNESS, ReviewStatus.FIX, "; ".join(result.reasons),
                   repair="produce edits that apply cleanly to the current files")]
    if result.commits != 0:
        return [_f(C.SCOPE_VIOLATION, ReviewStatus.BLOCK, "the worktree has commits; nothing may commit")]
    return []


def _scope_findings(request: ExecutionApprovalRequest, result: ExecutionResult) -> list[ReviewFinding]:
    approved = set(request.binding.targets)
    actual = set(result.files_changed)
    out = [_f(C.UNEXPECTED_FILE, ReviewStatus.BLOCK, f"{p} changed but was not approved", p)
           for p in sorted(actual - approved)]
    out += [_f(C.MISSING_REQUIREMENT, ReviewStatus.FIX, f"{p} was approved but did not change", p,
               repair=f"make the approved change in {p}") for p in sorted(approved - actual)]
    return out


def _check_findings(result: ExecutionResult, code_changed: bool) -> list[ReviewFinding]:
    out = []
    ran_tests = False
    for executed in result.checks:
        status = executed.result.status
        if status == CheckStatus.FAILED:
            out.append(_f(C.REGRESSION, ReviewStatus.FIX,
                          f"{executed.check.description} failed: {executed.result.output[-600:]}",
                          repair=f"make '{executed.check.description}' pass"))
        if status == CheckStatus.PASSED and executed.argv and "pytest" in executed.argv:
            ran_tests = True
    if code_changed and not ran_tests:
        out.append(_f(C.TEST_GAP, ReviewStatus.FIX, "no test ran against the changed code",
                      repair="add or update a test that covers the change"))
    return out


def _overlay_findings(request: ExecutionApprovalRequest, overlay: OverlayRefresh) -> list[ReviewFinding]:
    out = []
    planned = set(request.change.plan.symbols_to_change)
    for path, extraction in overlay.extractions.items():
        if extraction.error:
            out.append(_f(C.CORRECTNESS, ReviewStatus.FIX, f"{path} no longer parses: {extraction.error}", path,
                          repair=f"fix the syntax of {path}"))
    defined = {s.name for e in overlay.extractions.values() for s in e.definitions}
    planned_files = set(request.change.plan.files_to_change) & set(overlay.extractions)
    for name in sorted(planned):
        short = name.rsplit(".", 1)[-1]
        if planned_files and short not in defined:
            out.append(_f(C.REGRESSION, ReviewStatus.FIX, f"{name} is no longer defined in the changed files",
                          repair=f"keep {name} defined"))
    return out


def review_execution(request: ExecutionApprovalRequest, result: ExecutionResult, context: TaskContext,
                     reviewer: Reviewer, overlay: OverlayRefresh, impact: ImpactReport) -> ReviewResult:
    findings = _status_findings(result)
    if result.status == "executed":
        code_changed = any(not is_test_path(p) and not is_config_path(p) for p in result.files_changed)
        findings += _scope_findings(request, result)
        findings += _check_findings(result, code_changed)
        findings += _overlay_findings(request, overlay)
        if impact.risk.rank >= 2:
            findings.append(_f(C.RISKY_CHANGE, ReviewStatus.PASS, "high-risk change: " + impact.explain()))
        base = reviewer.review(ReviewRequest(request.task, request.change.plan, request.change.proposal,
                                             context, result.diff, result.check_results))
        findings += list(base.findings)
    return verdict(findings, bool(result.check_results))


def impact_of(intelligence: RepositoryIntelligence, result: ExecutionResult,
              request: ExecutionApprovalRequest) -> ImpactReport:
    return ImpactAnalyzer(intelligence.graph).analyze(result.files_changed or request.binding.targets,
                                                      request.change.plan.symbols_to_change)
