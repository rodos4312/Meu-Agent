"""The approval boundary and the hand-off to MEU's existing safe execution layer.

PLAN → PROPOSAL → REVIEW → **approval** → safe execution. Nothing in ``meu_coding``
mutates a repository. A reviewed proposal becomes an :class:`ApprovalRequest`; only
:func:`approve`, given an explicit positive :class:`ApprovalDecision` whose fingerprint
matches that exact request, produces an :class:`ApprovedChange`. Executors accept only an
``ApprovedChange``.

:class:`MeuToolCallAdapter` translates an approved change into calls of MEU's own
``patch`` and ``write_file`` tools. It returns the calls as data; the caller dispatches
them through MEU's normal tool path, where the write guards, approval prompts, stale-file
checks and V4A validation apply unchanged. Worktree isolation is a protocol for Phase 3,
to be implemented on top of the existing worktree system, never beside it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from meu_coding.coding_interfaces import (
    CheckResult,
    CheckSpec,
    CodeChangeProposal,
    EditAction,
    EditOperation,
    EditStrategy,
    ImplementationPlan,
    ReviewResult,
    ReviewStatus,
)


class ApprovalError(Exception):
    pass


def proposal_fingerprint(proposal: CodeChangeProposal) -> str:
    """SHA-256 over the canonical operations: any change to any edit changes it."""
    canonical = json.dumps([asdict(op) for op in proposal.operations], sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalRequest:
    plan: ImplementationPlan
    proposal: CodeChangeProposal
    review: ReviewResult
    fingerprint: str

    @classmethod
    def for_review(cls, plan: ImplementationPlan, proposal: CodeChangeProposal,
                   review: ReviewResult) -> ApprovalRequest:
        if review.status != ReviewStatus.PASS:
            raise ApprovalError(f"only a passed review can ask for approval (got {review.status.value})")
        return cls(plan, proposal, review, proposal_fingerprint(proposal))

    def summary(self) -> str:
        lines = [self.plan.summary, f"risk: {self.plan.risk.value}", "changes:"]
        lines += [f"  {d}" for d in self.proposal.change_descriptions]
        return "\n".join(lines)


@dataclass(frozen=True)
class ApprovalDecision:
    """Recorded by the user / MEU approval UI, never by a Coding Engine component."""

    approved: bool
    approver: str
    fingerprint: str
    note: str = ""


_APPROVAL_SEAL = object()


@dataclass(frozen=True)
class ApprovedChange:
    request: ApprovalRequest
    decision: ApprovalDecision
    _seal: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _APPROVAL_SEAL:
            raise ApprovalError("an ApprovedChange can only be created by approve()")


def approve(request: ApprovalRequest, decision: ApprovalDecision) -> ApprovedChange:
    if not decision.approved:
        raise ApprovalError(f"change was not approved by {decision.approver or 'anyone'}")
    if not decision.approver:
        raise ApprovalError("an approval must name its approver")
    if decision.fingerprint != request.fingerprint or proposal_fingerprint(request.proposal) != request.fingerprint:
        raise ApprovalError("approval does not match the reviewed proposal")
    if request.review.status != ReviewStatus.PASS:
        raise ApprovalError("only a passed review can be approved")
    return ApprovedChange(request, decision, _APPROVAL_SEAL)


# ── adapters to the existing MEU execution layer ────────────────────────────


@dataclass(frozen=True)
class ToolCall:
    """One call of an existing MEU tool (``patch`` / ``write_file``), as data."""

    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ExecutionReport:
    applied: bool
    tool_results: tuple[str, ...] = ()
    check_results: tuple[CheckResult, ...] = ()
    diff: str = ""


class ExecutionAdapter(Protocol):
    """Applies an approved change through MEU's safe tooling (Phase 3)."""

    def execute(self, change: ApprovedChange) -> ExecutionReport: ...


class IsolatedWorkspace(Protocol):
    """Phase 3 seam over MEU's existing worktree system (``tools/subagent_worktree.py``):
    open a temporary worktree, apply there, run checks, show the diff; merging or
    committing stays a separate, explicitly approved step outside this protocol."""

    def open(self, task_id: str) -> str: ...

    def apply(self, workspace: str, change: ApprovedChange) -> ExecutionReport: ...

    def run_checks(self, workspace: str, checks: tuple[CheckSpec, ...]) -> tuple[CheckResult, ...]: ...

    def diff(self, workspace: str) -> str: ...

    def close(self, workspace: str) -> None: ...


class MeuToolCallAdapter:
    """Approved change → MEU ``patch`` / ``write_file`` tool calls. Builds data only."""

    def tool_calls(self, change: ApprovedChange) -> tuple[ToolCall, ...]:
        if not isinstance(change, ApprovedChange):
            raise ApprovalError("tool calls are built only for an approved change")
        return tuple(_tool_call(op) for op in change.request.proposal.operations)


def _tool_call(op: EditOperation) -> ToolCall:
    if op.action == EditAction.DELETE:
        return ToolCall("patch", {"mode": "patch",
                                  "patch": f"*** Begin Patch\n*** Delete File: {op.path}\n*** End Patch\n"})
    if op.strategy == EditStrategy.WHOLE_FILE:
        return ToolCall("write_file", {"path": op.path, "content": op.content or ""})
    if op.strategy == EditStrategy.SEARCH_REPLACE:
        return ToolCall("patch", {"mode": "replace", "path": op.path,
                                  "old_string": op.search, "new_string": op.replace})
    if op.strategy == EditStrategy.V4A_PATCH:
        return ToolCall("patch", {"mode": "patch", "patch": op.patch})
    return ToolCall("patch", {"mode": "patch", "patch": unified_to_v4a(op.patch or "")})


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _diff_path(header: str) -> str | None:
    path = header[4:].split("\t", 1)[0].strip()
    if path == "/dev/null":
        return None
    return path[2:] if path[:2] in ("a/", "b/") else path


def _file_header(old: str | None, new: str | None) -> tuple[str, str]:
    if new is None:
        return "delete", f"*** Delete File: {old}"
    if old is None:
        return "add", f"*** Add File: {new}"
    return "update", f"*** Update File: {new}"


def _hunk_line(mode: str | None, line: str) -> str | None:
    if mode == "update" and _HUNK.match(line):
        return "@@"
    if mode == "update" and line[:1] in ("+", "-", " "):
        return line
    if mode == "add" and line.startswith("+"):
        return line
    return None


def unified_to_v4a(diff: str) -> str:
    """Convert a unified diff into the V4A format MEU's ``patch`` tool applies.

    Hunk line numbers are dropped (V4A anchors on context), ``/dev/null`` sides become
    Add / Delete operations. Malformed input yields a patch MEU's parser will reject.
    """
    out = ["*** Begin Patch"]
    lines = diff.splitlines()
    mode: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            mode, header = _file_header(_diff_path(line), _diff_path(lines[i + 1]))
            out.append(header)
            i += 2
            continue
        converted = _hunk_line(mode, line)
        if converted is not None:
            out.append(converted)
        i += 1
    out.append("*** End Patch")
    return "\n".join(out) + "\n"
