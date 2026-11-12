"""Integration and PR-preview operations of ``CodingTaskService`` (a mixin; one topic per file).

READY_TO_INTEGRATE (stage ``committed``) → PREVIEW (read-only drift and conflict analysis) →
explicit approval naming the preview token → INTEGRATING (isolated integration worktree,
replay, re-validation) → final-diff review → INTEGRATED or BLOCKED. Then a local PR preview the
user can edit, cancel or mark for later. Nothing here merges into the target branch, pushes,
creates a remote branch or opens a PR.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from meu_coding.coding_interfaces import (
    CheckKind,
    CheckResult,
    CheckSpec,
    CheckStatus,
    FindingCategory,
    ReviewFinding,
    ReviewRequest,
    ReviewStatus,
)
from meu_coding.coding_result import ResultState
from meu_coding.integration import (
    APPLICABLE,
    IntegrationOutcome,
    IntegrationPreview,
    IntegrationRefused,
    apply_integration,
    preview_integration,
)
from meu_coding.pr_preview import build_pr_preview, remote_names
from meu_coding.reviewer import Reviewer, verdict

logger = logging.getLogger(__name__)
C = FindingCategory


def _checks(planned: list[dict[str, Any]]) -> tuple[CheckSpec, ...]:
    return tuple(CheckSpec(CheckKind(c["kind"]), c.get("description", c["kind"]), tuple(c.get("targets") or ()))
                 for c in planned)


def _integration_findings(record, outcome: IntegrationOutcome) -> list[ReviewFinding]:
    result = record.result
    findings: list[ReviewFinding] = []
    if outcome.status != "integrated":
        return [ReviewFinding(C.SCOPE_VIOLATION, ReviewStatus.BLOCK, outcome.reason or "integration failed")]
    if sorted(outcome.final_files) != sorted(result.changed_files):
        findings.append(ReviewFinding(C.UNEXPECTED_FILE, ReviewStatus.BLOCK,
                                      "The integration changed different files than the reviewed result: "
                                      + ", ".join(sorted(set(outcome.final_files) ^ set(result.changed_files)))))
    for check in outcome.checks:
        if check["status"] == CheckStatus.FAILED.value:
            findings.append(ReviewFinding(C.REGRESSION, ReviewStatus.FIX,
                                          f"{check['check']} failed after integration: {check.get('output', '')[-300:]}",
                                          repair="fix the failing check before integrating"))
    if not any(c["kind"] == "unit_test" and c["status"] == "passed" for c in outcome.checks):
        findings.append(ReviewFinding(C.TEST_GAP, ReviewStatus.FIX, "no test passed on the integration branch"))
    if outcome.patch_changed:
        findings.append(ReviewFinding(C.RISKY_CHANGE, ReviewStatus.PASS,
                                      "Replaying onto the moved target changed the patch; it was reviewed again."))
    return findings


def _model_review(record, outcome: IntegrationOutcome) -> list[ReviewFinding]:
    """The independent reviewer reads the FINAL integration diff (live sessions only)."""
    session, models = record.session, record.models
    if session is None or models is None or models.review is None or session.planning is None:
        return []
    planning = session.planning
    results = tuple(CheckResult(f"{c['kind']}:", CheckStatus(c["status"]), c.get("output", "")) for c in outcome.checks)
    request = ReviewRequest(record.task, planning.plan, planning.proposal, session.context, outcome.final_diff, results)
    return list(Reviewer(models.review).review(request).findings)


class IntegrationMixin:
    # ── preview (read-only) ─────────────────────────────────────────────────

    def integration_preview(self, task_id: str) -> dict[str, Any]:
        from meu_coding.task_service import Stage, TaskError

        record = self._require(task_id)
        with record.lock:
            result = record.result
            if record.stage not in (Stage.COMMITTED, Stage.INTEGRATION_PREVIEW) or result is None \
                    or not result.result_commit:
                raise TaskError("Integration is available after Reviewer PASS, Keep and a worktree commit.")
            started = time.perf_counter()
            try:
                preview = preview_integration(
                    task_id=record.task_id, repo_root=record.project_root, source_branch=result.worktree_branch,
                    target_branch=result.target_branch, base_commit=result.base_commit,
                    result_commit=result.result_commit, approved_files=list(result.changed_files))
            except IntegrationRefused as exc:
                raise TaskError(str(exc)) from None
            record.integration_preview = preview
            summary = {k: v for k, v in preview.to_dict().items() if k != "token"}
            record.integration = {"preview": summary, "status": preview.status.value}
            record.audit.integration = dict(record.integration)
            record.timings["integration_preview"] = round(time.perf_counter() - started, 3)
            self._set(record, Stage.INTEGRATION_PREVIEW)
        return self.get(task_id)

    def integration_cancel(self, task_id: str, source: str = "desktop") -> dict[str, Any]:
        from meu_coding.task_service import Stage, TaskError

        record = self._require(task_id)
        with record.lock:
            if record.stage != Stage.INTEGRATION_PREVIEW:
                raise TaskError("There is no integration preview to cancel.")
            record.integration_preview = None
            record.audit.decisions.append({"decision": "integration_cancel", "source": source,
                                           "at": round(time.time(), 3)})
            self._set(record, Stage.COMMITTED)
        return self.get(task_id)

    # ── apply (explicit approval only) ──────────────────────────────────────

    def integration_approve(self, task_id: str, *, token: str, confirmed: bool,
                            source: str = "desktop") -> dict[str, Any]:
        from meu_coding.task_service import Stage, TaskError

        record = self._require(task_id)
        with record.lock:
            preview: IntegrationPreview | None = record.integration_preview
            if record.stage != Stage.INTEGRATION_PREVIEW or preview is None:
                raise TaskError("Preview the integration first.")
            if confirmed is not True:
                raise TaskError("Integration not confirmed.")
            if token != preview.token:
                raise TaskError("This integration preview is out of date — preview the integration again.")
            if preview.status not in APPLICABLE:
                raise TaskError(f"Integration is blocked: {preview.explanation}")
            record.audit.decisions.append({"decision": "integrate", "source": source, "target_head": preview.target_head,
                                           "result_commit": preview.result_commit, "at": round(time.time(), 3)})
            self._set(record, Stage.INTEGRATING)  # consumed before the worker starts
        self.spawn(lambda: self._integrate(record, preview), f"coding-integrate-{task_id[:8]}")
        return self.get(task_id)

    def _integrate(self, record, preview: IntegrationPreview) -> None:
        from meu_coding.task_service import Stage

        started = time.perf_counter()
        try:
            adapter = self.adapter_factory()
            outcome = apply_integration(preview, repo_root=record.project_root, task_id=record.task_id,
                                        workspace=adapter.workspace, checks=_checks(record.result.planned_checks),
                                        executor_factory=adapter.executor_factory)
            findings = _integration_findings(record, outcome)
            if outcome.status == "integrated":
                findings += _model_review(record, outcome)
            review = verdict(findings, bool(outcome.checks))
        except Exception as exc:  # integration boundary: report, never leave INTEGRATING spinning
            logger.warning("coding task %s: integration failed", record.task_id, exc_info=True)
            self._fail(record, f"Integration failed: {type(exc).__name__}: {exc}")
            return
        record.integration.update({
            "status": outcome.status if review.status == ReviewStatus.PASS else "blocked",
            "branch": outcome.branch, "worktree_path": outcome.worktree_path,
            "integration_commit": outcome.integration_commit, "target_head": preview.target_head,
            "final_files": outcome.final_files, "final_stat": outcome.final_stat, "patch_changed": outcome.patch_changed,
            "checks": [{k: c[k] for k in ("check", "kind", "status")} for c in outcome.checks],
            "review": {"verdict": review.status.value, "rationale": review.rationale[:500]},
            "reason": outcome.reason})
        record.integration_final_diff = outcome.final_diff
        record.audit.integration = dict(record.integration)
        record.timings["integration_apply"] = round(time.perf_counter() - started, 3)
        if outcome.status == "integrated" and review.status == ReviewStatus.PASS:
            record.result.advance(ResultState.INTEGRATED)
            record.audit.result = record.result.to_dict()
            self._set(record, Stage.INTEGRATED)
        else:
            self._set(record, Stage.BLOCKED, outcome.reason or review.rationale)

    # ── PR preview (local data only) ────────────────────────────────────────

    def pr_prepare(self, task_id: str) -> dict[str, Any]:
        from meu_coding.task_service import Stage, TaskError

        record = self._require(task_id)
        with record.lock:
            if record.stage != Stage.INTEGRATED or record.result is None:
                raise TaskError("A PR preview is available after a validated integration.")
            plan = record.session.planning.plan if record.session and record.session.planning else None
            record.pr = build_pr_preview(
                description=record.task.description, plan_summary=plan.summary if plan else "",
                risk=plan.risk.value if plan else "unknown", result=record.result.to_dict(),
                integration=record.integration, reviewer=record.integration.get("review", {}),
                remotes=remote_names(record.project_root))
            record.audit.pr = dict(record.pr)
            self._save(record)
        return self.get(task_id)

    def pr_update(self, task_id: str, *, title: str | None = None, body: str | None = None,
                  status: str | None = None) -> dict[str, Any]:
        from meu_coding.task_service import TaskError

        record = self._require(task_id)
        with record.lock:
            if record.pr is None or record.pr.get("status") == "cancelled":
                raise TaskError("Prepare a PR preview first.")
            if status not in (None, "draft", "cancelled", "approved_for_later"):
                raise TaskError("Unknown PR preview status.")
            if title is not None:
                record.pr["title"] = " ".join(title.split())[:200] or record.pr["title"]
            if body is not None:
                record.pr["body"] = body[:20_000]
            if status is not None:
                record.pr["status"] = status
            record.pr["remote_available"] = False  # the local draft never creates a remote PR
            record.pr["updated_at"] = round(time.time(), 3)
            record.audit.pr = dict(record.pr)
            self._save(record)
        return self.get(task_id)
