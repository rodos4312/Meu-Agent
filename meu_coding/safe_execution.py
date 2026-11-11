"""Approval binding (fingerprint v2) and the SafeExecutionAdapter.

Phase 2 approval binds a reviewed proposal. Execution approval additionally binds the task,
the exact edit payload, the target files with their current content hashes, the exact
expected result (previewed with MEU's own patch engine before anyone approves), and the
repository identity (root, branch, HEAD). Each approval has a single-use id issued by the
adapter's ledger; repairs revoke the previous id. Anything that changes after approval
makes the approval fail to verify, and nothing is reused silently.

Execution happens only in an isolated worktree (``meu_coding.workspace``): the parent
checkout is read, never written. After applying, the actual diff and file hashes must match
the approved preview exactly, checks run through the command policy, and a check that
modifies the worktree, or any commit, blocks the result. Nothing is committed, merged or
pushed.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meu_coding.coding_interfaces import (
    CheckResult,
    CheckSpec,
    CodeChangeProposal,
    CodingTask,
    EditAction,
    EditStrategy,
    ImplementationPlan,
)
from meu_coding.edit_strategy import touched_paths
from meu_coding.execution import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovedChange,
    approve,
    proposal_fingerprint,
)
from meu_coding.relevance import is_test_path
from meu_coding.schemas import safe_path_problem
from meu_coding.scope import is_protected
from meu_coding.test_executor import ExecutedCheck, TestExecutor
from meu_coding.workspace import (
    MemoryFileOps,
    MeuWorktreeWorkspace,
    RepoIdentity,
    WorkspaceError,
    Worktree,
    WorktreeFileOps,
    apply_operations,
    changed_files,
    combined_patch,
    decode_text,
    diff_counts,
    file_sha256,
    read_identity,
    text_sha256,
)

EXECUTABLE_STRATEGIES = frozenset(EditStrategy)
_V4A_DESTRUCTIVE = ("*** Delete File:", "*** Move File:")


class ExecutionBlocked(Exception):
    def __init__(self, reasons: list[str] | str) -> None:
        reasons = [reasons] if isinstance(reasons, str) else reasons
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


# ── scope re-validation (independent of every earlier stage) ────────────────


def scope_errors(task: CodingTask, plan: ImplementationPlan, proposal: CodeChangeProposal) -> list[str]:
    errors = []
    allowed = plan.allowed_paths
    protected = task.constraints.protected_paths
    if not proposal.operations:
        errors.append("the proposal has no edits")
    for op in proposal.operations:
        if op.strategy not in EXECUTABLE_STRATEGIES:
            errors.append(f"{op.path}: strategy {op.strategy} is not executable")
        if op.action == EditAction.DELETE:
            errors.append(f"{op.path}: deleting files is not allowed")
        if op.patch and any(marker in op.patch for marker in _V4A_DESTRUCTIVE):
            errors.append(f"{op.path}: patch deletes or moves files")
        for path in touched_paths(op):
            problem = safe_path_problem(path)
            if problem:
                errors.append(problem)
            elif is_protected(path, protected):
                errors.append(f"{path} is protected")
            elif path not in allowed:
                errors.append(f"{path} is outside the approved plan")
            elif path != op.path:
                errors.append(f"{op.path}: patch also edits {path}")
    targets = {op.path for op in proposal.operations}
    if len(targets) > task.constraints.max_files:
        errors.append(f"{len(targets)} files exceed the limit of {task.constraints.max_files}")
    return errors


# ── binding and approval ────────────────────────────────────────────────────


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def task_digest(task: CodingTask) -> str:
    c = task.constraints
    return _digest([task.description, list(task.explicit_files), task.recent_diff or "", task.model_id,
                    list(c.protected_paths), c.allow_new_files, c.allow_deletes, c.max_files, c.require_tests])


def payload_digest(proposal: CodeChangeProposal) -> str:
    whole = [[op.path, op.content] for op in proposal.operations
             if op.strategy == EditStrategy.WHOLE_FILE and op.action == EditAction.UPDATE]
    return _digest([combined_patch(proposal.operations), whole])


@dataclass(frozen=True)
class ExecutionBinding:
    task_digest: str
    proposal_fingerprint: str
    payload_digest: str
    targets: tuple[str, ...]
    base_hashes: tuple[tuple[str, str | None], ...]
    expected_hashes: tuple[tuple[str, str], ...]
    repo_root: str
    branch: str
    base_commit: str

    def fingerprint(self) -> str:
        return _digest(self.__dict__)


@dataclass(frozen=True)
class ExecutionApprovalRequest:
    approval_id: str
    task: CodingTask
    change: ApprovalRequest
    binding: ExecutionBinding
    preview_diff: str

    @property
    def fingerprint(self) -> str:
        return self.binding.fingerprint()

    def summary(self) -> str:
        return (f"{self.change.summary()}\nrepository: {self.binding.repo_root} @ {self.binding.branch} "
                f"{self.binding.base_commit[:12]}\napproval: {self.approval_id} {self.fingerprint[:16]}")


@dataclass(frozen=True)
class ExecutionDecision:
    """Recorded by the user / MEU approval UI. Never produced by a model."""

    approved: bool
    approver: str
    approval_id: str
    fingerprint: str


_SEAL = object()


@dataclass(frozen=True)
class ApprovedExecution:
    request: ExecutionApprovalRequest
    decision: ExecutionDecision
    change: ApprovedChange
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise ApprovalError("an ApprovedExecution can only be created by approve_execution()")


def _current_binding(request: ExecutionApprovalRequest) -> None:
    """Raise unless the request still describes its own proposal and task."""
    proposal = request.change.proposal
    binding = request.binding
    if proposal_fingerprint(proposal) != binding.proposal_fingerprint:
        raise ApprovalError("the proposal changed after the approval was prepared")
    if payload_digest(proposal) != binding.payload_digest:
        raise ApprovalError("the edit payload changed after the approval was prepared")
    if task_digest(request.task) != binding.task_digest:
        raise ApprovalError("the task changed after the approval was prepared")
    if tuple(sorted({op.path for op in proposal.operations})) != binding.targets:
        raise ApprovalError("the target files changed after the approval was prepared")


def approve_execution(request: ExecutionApprovalRequest, decision: ExecutionDecision) -> ApprovedExecution:
    if not isinstance(request, ExecutionApprovalRequest) or not isinstance(decision, ExecutionDecision):
        raise ApprovalError("approval needs an ExecutionApprovalRequest and an ExecutionDecision")
    if not decision.approved:
        raise ApprovalError("execution was not approved")
    if not decision.approver.strip():
        raise ApprovalError("an approval must name its approver")
    if decision.approval_id != request.approval_id:
        raise ApprovalError("the decision is for a different approval")
    _current_binding(request)
    if decision.fingerprint != request.fingerprint:
        raise ApprovalError("the decision does not match the prepared approval")
    change = approve(request.change, ApprovalDecision(True, decision.approver, request.change.fingerprint))
    return ApprovedExecution(request, decision, change, _SEAL)


# ── results ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionResult:
    status: str  # "executed" | "blocked" | "failed"
    reasons: tuple[str, ...]
    approval_id: str
    fingerprint: str
    worktree_path: str = ""
    worktree_branch: str = ""
    base_commit: str = ""
    files_changed: tuple[str, ...] = ()
    additions: int = 0
    deletions: int = 0
    diff: str = ""
    checks: tuple[ExecutedCheck, ...] = ()
    check_results: tuple[CheckResult, ...] = ()
    commits: int | None = None
    commit_status: str = "not committed"
    worktree_state: dict[str, Any] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def executed(self) -> bool:
        return self.status == "executed"


# ── the adapter ─────────────────────────────────────────────────────────────


def _read_parent(root: Path, rel: str) -> str | None:
    target = WorktreeFileOps(root).confine(rel)
    if not target.exists():
        return None
    try:
        return decode_text(target.read_bytes())[0]
    except UnicodeDecodeError:
        raise ExecutionBlocked(f"{rel} is not UTF-8 text") from None


@dataclass
class SafeExecutionAdapter:
    workspace: MeuWorktreeWorkspace = field(default_factory=MeuWorktreeWorkspace)
    executor_factory: Callable[[Path, tuple[str, ...]], TestExecutor] = (
        lambda root, extra: TestExecutor(root, extra_test_targets=extra))
    _issued: dict[str, str] = field(default_factory=dict)  # approval id → "pending" | "revoked" | "used"

    # approval preparation ---------------------------------------------------

    def prepare(self, task: CodingTask, change: ApprovalRequest, repo_root: str | Path) -> ExecutionApprovalRequest:
        """Validate scope, bind the workspace identity and preview the exact result."""
        errors = scope_errors(task, change.plan, change.proposal)
        if errors:
            raise ExecutionBlocked(errors)
        identity = read_identity(repo_root)
        root = Path(identity.root)
        targets = tuple(sorted({op.path for op in change.proposal.operations}))
        base = {path: _read_parent(root, path) for path in targets}
        preview = MemoryFileOps(dict(base))
        ok, error = apply_operations(change.proposal.operations, preview)
        if not ok:
            raise ExecutionBlocked(f"the proposal does not apply to the current files: {error}")
        if set(preview.written) - set(targets):
            raise ExecutionBlocked("the preview wrote files outside the targets")
        binding = ExecutionBinding(
            task_digest=task_digest(task), proposal_fingerprint=proposal_fingerprint(change.proposal),
            payload_digest=payload_digest(change.proposal), targets=targets,
            base_hashes=tuple((p, file_sha256(root / p)) for p in targets),
            expected_hashes=tuple(sorted((p, text_sha256(c)) for p, c in preview.written.items())),
            repo_root=identity.root, branch=identity.branch, base_commit=identity.head,
        )
        diff = "".join("".join(difflib.unified_diff((base[p] or "").splitlines(keepends=True),
                                                    preview.written[p].splitlines(keepends=True),
                                                    f"a/{p}", f"b/{p}")) for p in sorted(preview.written))
        request = ExecutionApprovalRequest(uuid.uuid4().hex, task, change, binding, diff)
        self._issued[request.approval_id] = "pending"
        return request

    def revoke(self, approval_id: str) -> None:
        if self._issued.get(approval_id) == "pending":
            self._issued[approval_id] = "revoked"

    # execution --------------------------------------------------------------

    def _verify(self, approved: ApprovedExecution) -> ExecutionApprovalRequest:
        if not isinstance(approved, ApprovedExecution):
            raise ExecutionBlocked("execution needs an approved execution")
        request = approved.request
        state = self._issued.get(request.approval_id)
        if state != "pending":
            raise ExecutionBlocked(f"approval {request.approval_id[:8]} is {state or 'unknown to this adapter'}")
        self._issued[request.approval_id] = "used"  # single use, even if execution fails
        try:
            _current_binding(request)
        except ApprovalError as exc:
            raise ExecutionBlocked(str(exc)) from None
        if approved.decision.fingerprint != request.fingerprint:
            raise ExecutionBlocked("approval fingerprint mismatch")
        errors = scope_errors(request.task, request.change.plan, request.change.proposal)
        if errors:
            raise ExecutionBlocked(errors)
        return request

    @staticmethod
    def _check_identity(binding: ExecutionBinding) -> None:
        current = read_identity(binding.repo_root)
        expected = RepoIdentity(binding.repo_root, binding.branch, binding.base_commit)
        if current != expected:
            raise ExecutionBlocked(f"workspace identity changed since approval ({expected} → {current})")
        root = Path(binding.repo_root)
        for path, digest in binding.base_hashes:
            if file_sha256(root / path) != digest:
                raise ExecutionBlocked(f"{path} changed since approval")

    def execute(self, approved: ApprovedExecution, checks: tuple[CheckSpec, ...] = ()) -> ExecutionResult:
        timings: dict[str, float] = {}
        started = time.perf_counter()
        approval_id = getattr(getattr(approved, "request", None), "approval_id", "")
        try:
            request = self._verify(approved)
            self._check_identity(request.binding)
        except (ExecutionBlocked, WorkspaceError) as exc:
            reasons = getattr(exc, "reasons", (str(exc),))
            return ExecutionResult("blocked", tuple(reasons), approval_id, "")
        timings["verify"] = time.perf_counter() - started
        worktree = None
        try:
            worktree = self.workspace.open(request.binding.repo_root)
            return self._run(request, worktree, checks, timings)
        except (ExecutionBlocked, WorkspaceError) as exc:
            reasons = getattr(exc, "reasons", (str(exc),))
            state = self._settle(worktree, wrote=worktree.touched) if worktree else {}
            return ExecutionResult("blocked", tuple(reasons), request.approval_id, request.fingerprint,
                                   *self._where(worktree), worktree_state=state, timings=_rounded(timings))

    @staticmethod
    def _where(worktree: Worktree | None) -> tuple[str, str, str]:
        if worktree is None:
            return "", "", ""
        return str(worktree.path), worktree.branch, worktree.base_commit

    def _settle(self, worktree: Worktree, *, wrote: bool) -> dict[str, Any]:
        """Untouched worktree → existing rules may prune it; touched → always kept."""
        return self.workspace.finalize(worktree, discard=not wrote)

    def _run(self, request: ExecutionApprovalRequest, worktree: Worktree, checks, timings) -> ExecutionResult:
        binding = request.binding
        if worktree.base_commit != binding.base_commit:
            raise ExecutionBlocked("the worktree is not based on the approved commit")
        for path, digest in binding.base_hashes:
            if file_sha256(worktree.path / path) != digest:
                raise ExecutionBlocked(f"{path} in the worktree differs from the approved base (stale)")
        mark = time.perf_counter()
        worktree.touched = True
        file_ops = WorktreeFileOps(worktree.path)
        ok, error = apply_operations(request.change.proposal.operations, file_ops)
        timings["apply"] = time.perf_counter() - mark
        if not ok:
            state = self._settle(worktree, wrote=bool(file_ops.written))
            return ExecutionResult("failed", (f"apply failed: {error}",), request.approval_id, request.fingerprint,
                                   *self._where(worktree), worktree_state=state, timings=_rounded(timings))
        before = self.workspace.diff(worktree)
        mismatch = self._mismatch(binding, worktree, before)
        if mismatch:
            return self._finish(request, worktree, before, (), "blocked", mismatch, timings)
        mark = time.perf_counter()
        changed = changed_files(before)
        executor = self.executor_factory(worktree.path, tuple(p for p in changed if is_test_path(p)))
        executor.run_all(checks)
        timings["checks"] = time.perf_counter() - mark
        after = self.workspace.diff(worktree)
        reasons = []
        if after.get("diff") != before.get("diff") or changed_files(after) != changed:
            reasons.append("running the checks modified the worktree")
        return self._finish(request, worktree, after, tuple(executor.executed),
                            "blocked" if reasons else "executed", reasons, timings)

    def _mismatch(self, binding: ExecutionBinding, worktree: Worktree, diff: dict[str, Any]) -> list[str]:
        expected = dict(binding.expected_hashes)
        reasons = []
        actual_changed = set(changed_files(diff))
        if actual_changed != set(expected):
            reasons.append(f"actual changed files {sorted(actual_changed)} differ from the approved "
                           f"{sorted(expected)}")
        for path, digest in expected.items():
            if file_sha256(worktree.path / path) != digest:
                reasons.append(f"{path} differs from the approved result")
        return reasons

    def _finish(self, request, worktree, diff, executed, status, reasons, timings) -> ExecutionResult:
        commits = self.workspace.commits_since_base(worktree)
        reasons = list(reasons)
        if commits != 0:
            reasons.append("a commit appeared in the worktree" if commits else "commit state unknown")
            status = "blocked"
        state = self._settle(worktree, wrote=True)
        additions, deletions = diff_counts(diff.get("diff", ""))
        return ExecutionResult(
            status, tuple(reasons), request.approval_id, request.fingerprint, *self._where(worktree),
            files_changed=changed_files(diff), additions=additions, deletions=deletions,
            diff=diff.get("diff", ""), checks=executed, check_results=tuple(e.result for e in executed),
            commits=commits, commit_status="not committed" if commits == 0 else "UNEXPECTED COMMIT",
            worktree_state=state, timings=_rounded(timings),
        )


def _rounded(timings: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 3) for k, v in timings.items()}
