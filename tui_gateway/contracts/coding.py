"""Coding Engine tasks (``coding.*``): plan → approval → isolated execution → keep/reject → commit.

Every method is profile-scoped (the task service is per profile home). The task view is
producer-owned (``meu_coding/task_views.py::snapshot``): the stable keys are typed, nested
sections travel as the producer builds them. Decisions name the exact approval id AND
fingerprint; a mismatch, replay or stale proposal is refused (5072).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import JsonValue
from .common import OpenModel, ProfileParams
from .registry import method


class CodingTaskView(OpenModel):
    """``meu_coding/task_views.py::snapshot``."""

    task_id: str
    stage: str
    stage_label: str
    description: str
    project: str
    error: str = ""
    busy: bool = False
    actions: dict[str, bool] = Field(default_factory=dict)
    plan: dict[str, JsonValue] | None = None
    approval: dict[str, JsonValue] | None = None
    execution: dict[str, JsonValue] | None = None
    commit: dict[str, JsonValue] | None = None
    remote: dict[str, JsonValue] | None = None


class CodingTaskResult(OpenModel):
    task: CodingTaskView


class CodingTaskRow(OpenModel):
    task_id: str
    description: str
    project: str
    stage: str


class CodingTaskListResult(OpenModel):
    tasks: list[CodingTaskRow]


class CodingStartParams(ProfileParams):
    description: str = Field(min_length=1, max_length=8_000)
    project_root: str = Field(min_length=1)
    explicit_files: list[str] = Field(default_factory=list, max_length=32)
    protected_paths: list[str] = Field(default_factory=list, max_length=64)


class CodingTaskParams(ProfileParams):
    task_id: str = Field(min_length=1)


class CodingDecideParams(CodingTaskParams):
    approval_id: str = Field(min_length=1)
    fingerprint: str = Field(min_length=64, max_length=64)
    decision: Literal["approve", "reject"]
    device: str | None = None


class CodingCommitConfirmParams(CodingTaskParams):
    message: str = Field(min_length=1, max_length=5_000)
    token: str = Field(min_length=1)
    confirmed: bool


class CodingIntegrationApproveParams(CodingTaskParams):
    token: str = Field(min_length=64, max_length=64)
    confirmed: bool


class CodingPrUpdateParams(CodingTaskParams):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)
    status: Literal["draft", "cancelled", "approved_for_later"] | None = None



RemoteKind = Literal["push", "pr", "merge"]


class CodingRemoteKindParams(CodingTaskParams):
    kind: RemoteKind


class CodingRemotePreviewParams(CodingRemoteKindParams):
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)
    method: Literal["merge", "squash", "rebase"] = "squash"


class CodingRemoteApproveParams(CodingRemoteKindParams):
    fingerprint: str = Field(min_length=64, max_length=64)
    confirmed: bool


class CodingRemoteRepairParams(CodingTaskParams):
    comment_ids: list[int] = Field(min_length=1, max_length=20)


class CodingReviewComment(OpenModel):
    id: int | None = None
    path: str = ""
    line: int | None = None
    author: str = ""
    body: str = ""


class CodingRemoteFeedbackResult(OpenModel):
    comments: list[CodingReviewComment]


method("coding.start", params=CodingStartParams, result=CodingTaskResult,
       doc="Start a coding task in a git project: analyze, plan, propose and review; ends awaiting approval.")
method("coding.get", params=CodingTaskParams, result=CodingTaskResult,
       doc="The task's current stage and views (approval preview, actual diff, review, commit preview).")
method("coding.list", params=ProfileParams, result=CodingTaskListResult,
       doc="Recent coding tasks of the profile, newest first (restored ones never resume).")
method("coding.decide", params=CodingDecideParams, result=CodingTaskResult,
       doc="Approve or reject the exact fingerprinted proposal; consumed once.")
method("coding.keep", params=CodingTaskParams, result=CodingTaskResult,
       doc="Keep the executed, reviewed worktree result (ready to commit only after Reviewer PASS).")
method("coding.reject", params=CodingTaskParams, result=CodingTaskResult,
       doc="Reject an executed result; worktrees follow the existing safe cleanup rules.")
method("coding.repair", params=CodingTaskParams, result=CodingTaskResult,
       doc="Ask for a repair after a FIX review; the new proposal needs a new approval.")
method("coding.commit.prepare", params=CodingTaskParams, result=CodingTaskResult,
       doc="Preview a local commit on the worktree branch: files, stat, suggested message, token.")
method("coding.commit.confirm", params=CodingCommitConfirmParams, result=CodingTaskResult,
       doc="Commit locally on the worktree branch with the user's message. Never pushes or merges.")
method("coding.integration.preview", params=CodingTaskParams, result=CodingTaskResult,
       doc="Read-only integration preview: target drift, conflicts, strategies and a preview token.")
method("coding.integration.approve", params=CodingIntegrationApproveParams, result=CodingTaskResult,
       doc="Apply the previewed result to an isolated integration branch, re-validate and re-review. Never merges.")
method("coding.integration.cancel", params=CodingTaskParams, result=CodingTaskResult,
       doc="Discard the integration preview; the committed worktree result stays ready to integrate.")
method("coding.pr.prepare", params=CodingTaskParams, result=CodingTaskResult,
       doc="Build a local PR preview from the integrated result. Nothing is sent to a remote.")
method("coding.pr.update", params=CodingPrUpdateParams, result=CodingTaskResult,
       doc="Edit, cancel or mark the local PR preview as approved for creation later.")
method("coding.remote.detect", params=CodingTaskParams, result=CodingTaskResult,
       doc="Detect the repository's remote, GitHub identity and credential availability (read-only).")
method("coding.remote.preview", params=CodingRemotePreviewParams, result=CodingTaskResult,
       doc="Read-only preview of a push, a PR creation or a merge, with the fingerprint its approval must name.")
method("coding.remote.approve", params=CodingRemoteApproveParams, result=CodingTaskResult,
       doc="Execute exactly the previewed push / PR creation / merge; single use, re-verified, never forced.")
method("coding.remote.cancel", params=CodingRemoteKindParams, result=CodingTaskResult,
       doc="Discard a pending remote preview without executing it.")
method("coding.remote.refresh", params=CodingTaskParams, result=CodingTaskResult,
       doc="Refresh the PR's state, checks, reviews and head/target drift on demand.")
method("coding.remote.feedback", params=CodingTaskParams, result=CodingRemoteFeedbackResult,
       doc="Read the PR's review comments (no code is edited).")
method("coding.remote.repair", params=CodingRemoteRepairParams, result=CodingTaskResult,
       doc="Start a NEW coding task from selected review comments; it needs its own approval.")
