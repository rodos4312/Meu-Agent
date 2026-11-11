"""CodingTaskService: the operational coding-task lifecycle behind the desktop (and, later,
mobile) approval UX.

One task = one ``CodingSession`` (Phases 1–3) plus a strict stage machine, a single-use
approval decision, keep/reject, an optional controlled local commit, and an audit record.
Work runs on a background thread started under the caller's profile context; UI calls only
read snapshots built from objects the engine already produced (no re-analysis, no diff or
test re-runs for display).

Integrity rules enforced here, on top of Phase 3:
- a decision must name the CURRENT approval id and fingerprint; anything else is refused;
- a decision is consumed once (the stage leaves AWAITING_APPROVAL under the task lock);
- a repair produces a new proposal and a new approval; the old one can never execute it;
- commit only from READY_TO_COMMIT (executed, tested, actual-diff PASS, user KEEP) and only
  with an explicit confirmation and a fresh preview token;
- nothing pushes, merges or commits on its own; the parent checkout is never written.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from meu_coding import task_audit
from meu_coding.architect import Architect
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import CodingTask, ReviewStatus, TaskConstraints
from meu_coding.coding_session import CodingSession, SessionState
from meu_coding.commit_flow import CommitPlan, CommitRefused, confirm_commit, prepare_commit
from meu_coding.execution import ApprovalError
from meu_coding.impact import ImpactAnalyzer
from meu_coding.intelligence import RepositoryIntelligence, analyze_repository
from meu_coding.reviewer import Reviewer
from meu_coding.safe_execution import ExecutionDecision, SafeExecutionAdapter
from meu_coding.task_views import friendly_error, snapshot
from meu_coding.workspace import Worktree, WorkspaceError, read_identity

logger = logging.getLogger(__name__)


class Stage(str, Enum):
    ANALYZING = "analyzing"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    TESTING = "testing"
    REVIEWING_DIFF = "reviewing_diff"
    AWAITING_KEEP_REJECT = "awaiting_keep_reject"
    KEPT = "kept"
    READY_TO_COMMIT = "ready_to_commit"
    COMMITTED = "committed"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    FAILED = "failed"


S = Stage
TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    S.ANALYZING: frozenset({S.PLANNING, S.BLOCKED, S.FAILED}),
    S.PLANNING: frozenset({S.CODING, S.BLOCKED, S.FAILED}),
    S.CODING: frozenset({S.REVIEWING, S.BLOCKED, S.FAILED}),
    S.REVIEWING: frozenset({S.CODING, S.AWAITING_APPROVAL, S.BLOCKED, S.FAILED}),
    S.AWAITING_APPROVAL: frozenset({S.EXECUTING, S.REJECTED}),
    S.EXECUTING: frozenset({S.TESTING, S.REVIEWING_DIFF, S.BLOCKED, S.FAILED}),
    S.TESTING: frozenset({S.REVIEWING_DIFF, S.BLOCKED, S.FAILED}),
    S.REVIEWING_DIFF: frozenset({S.AWAITING_KEEP_REJECT, S.BLOCKED, S.FAILED}),
    S.AWAITING_KEEP_REJECT: frozenset({S.READY_TO_COMMIT, S.KEPT, S.REJECTED, S.CODING}),
    S.KEPT: frozenset({S.REJECTED}),
    S.READY_TO_COMMIT: frozenset({S.COMMITTED, S.REJECTED}),
    S.BLOCKED: frozenset({S.REJECTED}),
    S.FAILED: frozenset({S.REJECTED}),
    S.COMMITTED: frozenset(),
    S.REJECTED: frozenset(),
}
BUSY_STAGES = frozenset({S.ANALYZING, S.PLANNING, S.CODING, S.REVIEWING, S.EXECUTING, S.TESTING, S.REVIEWING_DIFF})


class TaskError(Exception):
    """An actionable refusal for the UI (``message`` is shown as is)."""


@dataclass
class ModelBundle:
    planning: Any
    coding: Any
    review: Any
    routes: dict[str, str]
    source: str

    def used(self) -> dict[str, str]:
        used = dict(self.routes)
        last = getattr(self.coding, "last_route", None)
        if last is not None:
            used["coder_used"] = str(last)
        return used


def meu_models() -> ModelBundle:
    """Models from the profile's existing settings (Models by workload, else the main model)."""
    from hermes_cli.config import load_config_readonly

    from meu_coding.provider_adapter import provider_models, resolve_coding_routes

    resolution = resolve_coding_routes(load_config_readonly())
    models = provider_models(resolution.routes)
    r = resolution.routes
    routes = {"architect": str(r.architect), "coder": str(r.coder), "reviewer": str(r.reviewer)}
    if r.coder_simple:
        routes["coder_simple"] = str(r.coder_simple)
    return ModelBundle(models.planning, models.coding, models.review, routes, resolution.source)


def spawn_in_context(target: Callable[[], None], name: str) -> None:
    from agent.memory_provider import spawn_context_thread

    spawn_context_thread(target, name=name).start()


@dataclass
class TaskRecord:
    task_id: str
    project_root: str
    task: CodingTask
    audit: task_audit.AuditRecord
    stage: Stage = Stage.ANALYZING
    error: str = ""
    session: CodingSession | None = None
    models: ModelBundle | None = None
    commit_plan: CommitPlan | None = None
    commit_hash: str = ""
    cleanup: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    restored: bool = False


class CodingTaskService:
    def __init__(self, *, models_factory: Callable[[], ModelBundle] = meu_models,
                 adapter_factory: Callable[..., SafeExecutionAdapter] = SafeExecutionAdapter,
                 spawn: Callable[[Callable[[], None], str], None] = spawn_in_context,
                 intelligence_factory: Callable[[str], RepositoryIntelligence] = analyze_repository,
                 audit_directory: Path | None = None) -> None:
        self.models_factory = models_factory
        self.adapter_factory = adapter_factory
        self.spawn = spawn
        self.intelligence_factory = intelligence_factory
        self.audit_directory = audit_directory
        self.tasks: dict[str, TaskRecord] = {}
        self._intel: dict[str, RepositoryIntelligence] = {}
        self._root_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._restore()

    # ── stage machine ────────────────────────────────────────────────────────

    def _set(self, record: TaskRecord, stage: Stage, error: str = "") -> None:
        with record.lock:
            if stage == record.stage:
                return
            if stage not in TRANSITIONS[record.stage]:
                raise TaskError(f"Cannot move this task from {record.stage.value} to {stage.value}.")
            record.stage = stage
            record.history.append(stage.value)
            if error:
                record.error = friendly_error(error)
            elif stage not in (S.BLOCKED, S.FAILED):
                record.error = ""
            record.audit.stage(stage.value)
            self._save(record)

    def _save(self, record: TaskRecord) -> None:
        try:
            task_audit.save(record.audit, self.audit_directory)
        except (OSError, ValueError) as exc:
            record.error = record.error or f"Audit record could not be saved: {exc}"

    def _require(self, task_id: str) -> TaskRecord:
        record = self.tasks.get(str(task_id))
        if record is None:
            raise TaskError("No such coding task.")
        return record

    # ── start: analyze → plan → code → review → approval ────────────────────

    def start(self, description: str, project_root: str, explicit_files: tuple[str, ...] = (),
              protected_paths: tuple[str, ...] = ()) -> dict[str, Any]:
        text = (description or "").strip()
        if not text:
            raise TaskError("Describe the coding task first.")
        try:
            identity = read_identity(project_root)
        except WorkspaceError:
            raise TaskError("Choose a project folder that is a git repository with at least one commit.") from None
        try:
            models = self.models_factory()
        except Exception as exc:  # missing routes/credentials: actionable, nothing started
            logger.info("coding task: no usable model route", exc_info=True)
            raise TaskError(friendly_error(str(exc)) or "No coding model is configured.") from None
        task_id = uuid.uuid4().hex
        task = CodingTask(text, TaskConstraints(protected_paths=tuple(protected_paths)),
                          explicit_files=tuple(explicit_files))
        audit = task_audit.AuditRecord(task_id, identity.root, text[:200], models=dict(models.routes),
                                       route_source=models.source)
        record = TaskRecord(task_id, identity.root, task, audit, models=models, history=[S.ANALYZING.value])
        audit.stage(S.ANALYZING.value)
        self.tasks[task_id] = record
        self._save(record)
        self.spawn(lambda: self._plan(record), f"coding-plan-{task_id[:8]}")
        return self.get(task_id)

    def _root_lock(self, root: str) -> threading.Lock:
        with self._lock:
            return self._root_locks.setdefault(root, threading.Lock())

    def _intelligence(self, root: str) -> RepositoryIntelligence:
        intel = self._intel.get(root)
        if intel is None:
            intel = self.intelligence_factory(root)
            self._intel[root] = intel
        else:
            intel.refresh_changed_files()  # changed files only; the index is reused
        return intel

    def _plan(self, record: TaskRecord) -> None:
        try:
            with self._root_lock(record.project_root):
                started = time.perf_counter()
                intel = self._intelligence(record.project_root)
                record.timings["analyze"] = round(time.perf_counter() - started, 3)
                session = self._session(record, intel)
                record.session = session
                state = session.start(record.task)
            self._after_session(record, state)
        except TaskError as exc:
            self._fail(record, str(exc))
        except Exception as exc:  # the UI must see a stage, never a silent dead thread
            logger.warning("coding task %s: planning failed", record.task_id, exc_info=True)
            self._fail(record, f"{type(exc).__name__}: {exc}")

    def _session(self, record: TaskRecord, intel: RepositoryIntelligence) -> CodingSession:
        models = record.models
        service = self

        class StageArchitect(Architect):
            def plan(self, context):
                service._set(record, S.PLANNING)
                return super().plan(context)

        class StageCoder(Coder):
            def propose(self, *args, **kwargs):
                service._set(record, S.CODING)
                return super().propose(*args, **kwargs)

        class StageReviewer(Reviewer):
            def review(self, request):
                after = record.stage in (S.EXECUTING, S.TESTING, S.REVIEWING_DIFF)
                service._set(record, S.REVIEWING_DIFF if after else S.REVIEWING)
                return super().review(request)

        adapter = self.adapter_factory()
        run_checks = adapter.executor_factory

        def testing_executor(root, extra):
            service._set(record, S.TESTING)
            return run_checks(root, extra)

        adapter.executor_factory = testing_executor
        return CodingSession(intel, StageCoder(models.coding), StageReviewer(models.review),
                             StageArchitect(ImpactAnalyzer(intel.graph), models.planning), adapter=adapter)

    def _after_session(self, record: TaskRecord, state: SessionState) -> None:
        session = record.session
        planning = session.planning
        if planning is not None and planning.plan is not None:
            plan_text = json.dumps([planning.plan.summary, planning.plan.files_to_change, planning.plan.steps])
            record.audit.plan_hash = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
        record.audit.models = record.models.used()
        if state == SessionState.AWAITING_APPROVAL:
            pending = session.pending
            record.audit.approval_id = pending.approval_id
            record.audit.approval_fingerprint = pending.fingerprint
            record.audit.proposal_fingerprint = pending.binding.proposal_fingerprint
            self._set(record, S.AWAITING_APPROVAL)
            return
        reason = session.blocked_reason or _planning_reason(planning)
        if record.stage in (S.ANALYZING,):
            self._set(record, S.PLANNING)
        self._set(record, S.BLOCKED, reason)

    def _fail(self, record: TaskRecord, message: str) -> None:
        with record.lock:
            record.audit.error = friendly_error(message)[:500]
            if S.FAILED in TRANSITIONS[record.stage]:
                self._set(record, S.FAILED, message)
            else:
                record.error = friendly_error(message)
                self._save(record)

    # ── approval decision (consumed once) ───────────────────────────────────

    def decide(self, task_id: str, *, approval_id: str, fingerprint: str, approve: bool,
               approver: str, device: str = "") -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            session = record.session
            pending = session.pending if session else None
            if record.stage != S.AWAITING_APPROVAL or pending is None:
                raise TaskError("This approval was already used or the task has moved on.")
            if approval_id != pending.approval_id or fingerprint != pending.fingerprint:
                raise TaskError("Proposal changed after approval — approval required again.")
            entry = {"decision": "approve" if approve else "reject", "approver": approver[:80], "device": device[:80],
                     "approval_id": approval_id, "fingerprint": fingerprint, "at": round(time.time(), 3)}
            record.audit.decisions.append(entry)
            if not approve:
                session.adapter.revoke(approval_id)
                session.pending = None
                record.audit.keep_reject = "rejected before execution"
                self._set(record, S.REJECTED)
                return self.get(task_id)
            decision = ExecutionDecision(True, approver or "desktop user", approval_id, fingerprint)
            self._set(record, S.EXECUTING)  # consumes the decision before any thread starts
        self.spawn(lambda: self._execute(record, decision), f"coding-exec-{task_id[:8]}")
        return self.get(task_id)

    def _execute(self, record: TaskRecord, decision: ExecutionDecision) -> None:
        try:
            attempt = record.session.execute(decision)
        except ApprovalError as exc:
            self._fail(record, str(exc))
            return
        except Exception as exc:  # execution boundary: report, never leave a stage spinning
            logger.warning("coding task %s: execution failed", record.task_id, exc_info=True)
            self._fail(record, f"{type(exc).__name__}: {exc}")
            return
        result = attempt.result
        record.audit.worktree = {"path": result.worktree_path, "branch": result.worktree_branch,
                                 "base_commit": result.base_commit}
        record.audit.checks = [{"check": e.check.description, "status": e.result.status.value} for e in result.checks]
        record.audit.reviewer_verdict = attempt.review.status.value
        record.timings.update({f"exec_{k}": v for k, v in attempt.timings.items()})
        if record.stage in (S.EXECUTING, S.TESTING):
            self._set(record, S.REVIEWING_DIFF)
        if not result.executed or attempt.review.status == ReviewStatus.BLOCK:
            self._set(record, S.BLOCKED, "; ".join(result.reasons) or attempt.review.rationale)
            return
        self._set(record, S.AWAITING_KEEP_REJECT)

    # ── keep / reject / repair ──────────────────────────────────────────────

    def keep(self, task_id: str) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            if record.stage != S.AWAITING_KEEP_REJECT:
                raise TaskError("Keep is available after execution and review.")
            started = time.perf_counter()
            last = record.session.attempts[-1]
            passed = last.result.executed and last.review.status == ReviewStatus.PASS
            record.audit.keep_reject = "kept"
            self._set(record, S.READY_TO_COMMIT if passed else S.KEPT)
            record.timings["keep"] = round(time.perf_counter() - started, 4)
        return self.get(task_id)

    def reject(self, task_id: str) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            if record.stage == S.AWAITING_APPROVAL:
                raise TaskError("Use Reject on the approval card to decline the proposal.")
            if S.REJECTED not in TRANSITIONS[record.stage]:
                raise TaskError("This task cannot be rejected now.")
            started = time.perf_counter()
            record.cleanup = self._cleanup(record)
            record.audit.keep_reject = "rejected"
            self._set(record, S.REJECTED)
            record.timings["reject"] = round(time.perf_counter() - started, 3)
        return self.get(task_id)

    def _cleanup(self, record: TaskRecord) -> dict[str, Any]:
        """Existing worktree rules decide for every attempt's worktree; uncertainty keeps it."""
        outcomes = []
        session = record.session
        for attempt in (session.attempts if session else []):
            result = attempt.result
            if not result.worktree_path or not Path(result.worktree_path).exists():
                continue
            info = {"path": result.worktree_path, "branch": result.worktree_branch,
                    "repo_root": record.project_root, "base_commit": result.base_commit}
            worktree = Worktree(Path(result.worktree_path), result.worktree_branch, result.base_commit,
                                record.project_root, info, touched=True)
            try:
                payload = session.adapter.workspace.finalize(worktree, discard=True)
            except Exception as exc:  # cleanup must never raise past a reject: keep and explain
                logger.warning("coding task %s: worktree cleanup failed", record.task_id, exc_info=True)
                payload = {"path": result.worktree_path, "pruned": False, "inspection_failed": True,
                           "note": f"cleanup raised {type(exc).__name__}"}
            outcomes.append(payload)
        return {"worktrees": outcomes}

    def repair(self, task_id: str) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            if record.stage != S.AWAITING_KEEP_REJECT or not record.session.can_repair:
                raise TaskError("A repair is available only after a review asked for fixes, up to 3 times.")
            self._set(record, S.CODING)
        self.spawn(lambda: self._repair(record), f"coding-repair-{task_id[:8]}")
        return self.get(task_id)

    def _repair(self, record: TaskRecord) -> None:
        try:
            with self._root_lock(record.project_root):
                state = record.session.repair()
            self._after_session(record, state)
        except Exception as exc:  # repair boundary: report, never leave a stage spinning
            logger.warning("coding task %s: repair failed", record.task_id, exc_info=True)
            self._fail(record, f"{type(exc).__name__}: {exc}")

    # ── commit (explicit, local, worktree branch only) ──────────────────────

    def commit_prepare(self, task_id: str) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            if record.stage != S.READY_TO_COMMIT:
                raise TaskError("Commit is available only after Reviewer PASS and Keep.")
            started = time.perf_counter()
            last = record.session.attempts[-1]
            result = last.result
            try:
                record.commit_plan = prepare_commit(
                    worktree_path=result.worktree_path, worktree_branch=result.worktree_branch,
                    base_commit=result.base_commit, parent_root=record.project_root,
                    reviewed_files=result.files_changed, reviewed_diff=result.diff,
                    task_description=record.task.description, reviewer_rationale=last.review.rationale)
            except (CommitRefused, WorkspaceError) as exc:
                raise TaskError(str(exc)) from None
            record.timings["commit_prepare"] = round(time.perf_counter() - started, 3)
            return self.get(task_id)

    def commit_confirm(self, task_id: str, *, message: str, token: str, confirmed: bool) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            if record.stage != S.READY_TO_COMMIT or record.commit_plan is None:
                raise TaskError("Prepare the commit first.")
            try:
                commit_hash = confirm_commit(record.commit_plan, message=message, token=token, confirmed=confirmed,
                                             parent_root=record.project_root)
            except (CommitRefused, WorkspaceError) as exc:
                raise TaskError(str(exc)) from None
            record.commit_hash = commit_hash
            record.audit.commit_hash = commit_hash
            self._set(record, S.COMMITTED)
        return self.get(task_id)

    # ── reads ───────────────────────────────────────────────────────────────

    def get(self, task_id: str) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            started = time.perf_counter()
            view = snapshot(record)
            view["timings"]["view_build"] = round(time.perf_counter() - started, 4)
            return view

    def list(self) -> list[dict[str, Any]]:
        rows = []
        for record in sorted(self.tasks.values(), key=lambda r: r.audit.created_at, reverse=True):
            rows.append({"task_id": record.task_id, "description": record.task.description[:200],
                         "project": record.project_root, "stage": record.stage.value,
                         "created_at": record.audit.created_at, "restored": record.restored})
        return rows

    # ── restart: show, never resume ─────────────────────────────────────────

    def _restore(self) -> None:
        for audit in task_audit.load_all(self.audit_directory):
            if audit.task_id in self.tasks:
                continue
            last = audit.stages[-1]["stage"] if audit.stages else S.FAILED.value
            try:
                stage = Stage(last)
            except ValueError:
                stage = S.FAILED
            record = TaskRecord(audit.task_id, audit.project, CodingTask(audit.description or "(restored task)"),
                                audit, stage=stage, restored=True)
            if stage not in (S.COMMITTED, S.REJECTED, S.BLOCKED, S.FAILED):
                where = audit.worktree.get("path") or "no worktree"
                record.error = (f"Meu restarted while this task was {stage.value}; nothing continues automatically. "
                                f"Worktree: {where} (preserved for inspection).")
                record.stage = S.FAILED
            self.tasks[audit.task_id] = record


def _planning_reason(planning) -> str:
    if planning is None:
        return "The task could not be planned."
    if planning.plan_errors:
        return "Plan refused: " + "; ".join(planning.plan_errors)
    review = planning.review
    return review.rationale if review is not None else "The proposal did not pass review."
