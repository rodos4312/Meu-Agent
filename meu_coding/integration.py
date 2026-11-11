"""Controlled integration of a committed worktree result back toward its target branch.

Two steps, each explicit:

1. ``preview_integration`` — read-only. Compares the task's base commit with the target
   branch's current head, lists what changed on the target since (drift), and asks git for a
   conflict verdict with ``git merge-tree --write-tree`` (writes no ref, touches no checkout).
   Status: CLEAN, NEEDS_REBASE_OR_REPLAY, CONFLICT or BLOCKED.
2. ``apply_integration`` — only after an explicit approval naming the preview token. Creates
   an isolated integration worktree with MEU's existing worktree system (branch naming follows
   its ``hermes-subagent/`` convention), replays the result commit there with ``cherry-pick``,
   validates (planned checks through the command policy), and returns the final diff for the
   Reviewer. The target branch, the parent checkout and every remote are never touched: no
   merge into the target, no push, no rebase of anything that exists.

All git calls run through MEU's hardened, bounded runner (no hooks, pager, editor, credential
helpers or attribute drivers).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

GIT_TIMEOUT = 60.0
MAX_DRIFT_COMMITS = 20


class IntegrationStatus(str, Enum):
    CLEAN = "clean"
    NEEDS_REBASE_OR_REPLAY = "needs_rebase_or_replay"
    CONFLICT = "conflict"
    BLOCKED = "blocked"


APPLICABLE = frozenset({IntegrationStatus.CLEAN, IntegrationStatus.NEEDS_REBASE_OR_REPLAY})
STRATEGIES = ("APPLY_COMMIT", "CHERRY_PICK_PREVIEW", "CREATE_PR_PREVIEW")


class IntegrationRefused(Exception):
    pass


@dataclass
class GitResult:
    returncode: int
    stdout: str
    stderr: str


def git(cwd: str, *args: str, input_text: str | None = None, repo_env: bool = False) -> GitResult:
    from hermes_cli._subprocess_compat import (
        bounded_probe_run,
        harden_git_argv,
        noninteractive_git_env,
        noninteractive_repo_git_env,
    )

    env = noninteractive_repo_git_env(cwd) if repo_env else noninteractive_git_env()
    if env is None:
        raise IntegrationRefused("Git filters in this repository could not be neutralised.")
    result = bounded_probe_run(["git", "-C", cwd, *harden_git_argv(list(args))], timeout=GIT_TIMEOUT, env=env,
                               input=input_text)
    if result is None:
        raise IntegrationRefused(f"git {args[0]} timed out or could not start")
    return GitResult(result.returncode, result.stdout or "", result.stderr or "")


def _rev(cwd: str, ref: str) -> str:
    out = git(cwd, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    return out.stdout.strip() if out.returncode == 0 else ""


@dataclass
class IntegrationPreview:
    task_id: str
    status: IntegrationStatus
    explanation: str
    source_branch: str
    target_branch: str
    base_commit: str
    target_head: str
    result_commit: str
    changed_files: list[str]
    diff_stat: str
    target_changed: bool
    drift_commits: list[str] = field(default_factory=list)
    drift_files: list[str] = field(default_factory=list)
    overlapping_files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    token: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


def _token(preview: IntegrationPreview) -> str:
    material = [preview.task_id, preview.result_commit, preview.target_head, preview.status.value,
                sorted(preview.changed_files)]
    return hashlib.sha256(json.dumps(material).encode("utf-8")).hexdigest()


def _conflicts(repo: str, target_head: str, result_commit: str) -> tuple[bool, list[str]]:
    """``merge-tree --write-tree``: exit 0 clean, 1 conflicted (paths listed), else error."""
    out = git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", target_head, result_commit)
    if out.returncode == 0:
        return False, []
    if out.returncode == 1:
        lines = [line.strip() for line in out.stdout.splitlines()[1:] if line.strip()]
        return True, lines
    raise IntegrationRefused(f"git merge-tree failed: {out.stderr.strip()[:200]}")


def _drift(repo: str, base: str, target_head: str) -> tuple[list[str], list[str]]:
    log = git(repo, "log", "--format=%h %s", f"--max-count={MAX_DRIFT_COMMITS}", f"{base}..{target_head}")
    files = git(repo, "diff", "--name-only", base, target_head)
    return ([line for line in log.stdout.splitlines() if line.strip()],
            sorted(line.strip() for line in files.stdout.splitlines() if line.strip()))


def _blocked(task_id: str, reason: str, **kwargs) -> IntegrationPreview:
    preview = IntegrationPreview(task_id=task_id, status=IntegrationStatus.BLOCKED, explanation=reason,
                                 source_branch=kwargs.get("source_branch", ""),
                                 target_branch=kwargs.get("target_branch", ""),
                                 base_commit=kwargs.get("base_commit", ""), target_head=kwargs.get("target_head", ""),
                                 result_commit=kwargs.get("result_commit", ""), changed_files=[], diff_stat="",
                                 target_changed=False, strategies=["CREATE_PR_PREVIEW"])
    preview.token = _token(preview)
    return preview


def preview_integration(*, task_id: str, repo_root: str, source_branch: str, target_branch: str, base_commit: str,
                        result_commit: str, approved_files: list[str]) -> IntegrationPreview:
    ids = {"source_branch": source_branch, "target_branch": target_branch, "base_commit": base_commit,
           "result_commit": result_commit}
    if not result_commit or _rev(repo_root, result_commit) != result_commit:
        return _blocked(task_id, "The worktree result commit no longer exists.", **ids)
    if _rev(repo_root, result_commit + "^") != base_commit:
        return _blocked(task_id, "The result commit does not sit directly on the approved base commit.", **ids)
    target_head = _rev(repo_root, "refs/heads/" + target_branch)
    if not target_head:
        return _blocked(task_id, f"The target branch {target_branch} does not exist.", **ids)
    files = git(repo_root, "diff", "--name-only", base_commit, result_commit).stdout.split()
    if sorted(files) != sorted(approved_files):
        return _blocked(task_id, "The committed files differ from the reviewed files.", target_head=target_head, **ids)
    stat = git(repo_root, "diff", "--stat", base_commit, result_commit).stdout.strip()
    conflicted, conflict_paths = _conflicts(repo_root, target_head, result_commit)
    changed = target_head != base_commit
    drift_commits, drift_files = _drift(repo_root, base_commit, target_head) if changed else ([], [])
    overlap = sorted(set(drift_files) & set(files))
    if conflicted:
        status = IntegrationStatus.CONFLICT
        explanation = ("The target branch changed the same lines since this task began: "
                       + ", ".join(conflict_paths or overlap) + ". Integration is blocked; nothing was changed.")
    elif changed:
        status = IntegrationStatus.NEEDS_REBASE_OR_REPLAY
        explanation = (f"The target branch moved {len(drift_commits)} commit(s) past the task's base. The result "
                       "replays cleanly onto it in a separate integration branch; it is re-validated and "
                       "re-reviewed there before anything else happens.")
    else:
        status = IntegrationStatus.CLEAN
        explanation = "The target branch has not changed since the task began."
    strategies = ["APPLY_COMMIT", "CHERRY_PICK_PREVIEW", "CREATE_PR_PREVIEW"] if status in APPLICABLE \
        else ["CREATE_PR_PREVIEW"]
    preview = IntegrationPreview(task_id, status, explanation, source_branch, target_branch, base_commit, target_head,
                                 result_commit, sorted(files), stat, changed, drift_commits, drift_files, overlap,
                                 conflict_paths, strategies)
    preview.token = _token(preview)
    return preview


@dataclass
class IntegrationOutcome:
    status: str  # "integrated" | "blocked" | "failed"
    reason: str
    branch: str = ""
    worktree_path: str = ""
    integration_commit: str = ""
    final_files: list[str] = field(default_factory=list)
    final_diff: str = ""
    final_stat: str = ""
    patch_changed: bool = False
    checks: list[dict[str, str]] = field(default_factory=list)
    worktree_state: dict[str, Any] = field(default_factory=dict)


def _patch_id(repo: str, a: str, b: str) -> str:
    diff = git(repo, "diff", a, b).stdout
    out = git(repo, "patch-id", "--stable", input_text=diff)
    return out.stdout.split()[0] if out.returncode == 0 and out.stdout.split() else ""


def _replay(path: str, result_commit: str) -> str:
    """Cherry-pick inside the isolated integration worktree; abort there on failure."""
    if not (git(path, "config", "user.name").stdout.strip() and git(path, "config", "user.email").stdout.strip()):
        raise IntegrationRefused("Set git user.name and user.email for this repository before integrating.")
    picked = git(path, "cherry-pick", result_commit, repo_env=True)
    if picked.returncode != 0:
        git(path, "cherry-pick", "--abort", repo_env=True)
        raise IntegrationRefused(f"The result does not replay cleanly: {picked.stderr.strip()[:300]}")
    return _rev(path, "HEAD")


def apply_integration(preview: IntegrationPreview, *, repo_root: str, task_id: str, workspace, checks,
                      executor_factory) -> IntegrationOutcome:
    """Replay the reviewed result onto the target head in a NEW isolated worktree and validate it."""
    if preview.status not in APPLICABLE:
        return IntegrationOutcome("blocked", f"Integration is not possible: {preview.explanation}")
    if _rev(repo_root, "refs/heads/" + preview.target_branch) != preview.target_head:
        return IntegrationOutcome("blocked", "The target branch changed after the preview — preview the "
                                             "integration again.")
    worktree = workspace.open(repo_root, f"integrate-{task_id[:12]}")
    try:
        if worktree.base_commit != preview.target_head:
            raise IntegrationRefused("The project checkout is not on the target branch head; switch to "
                                     f"{preview.target_branch} or preview again.")
        worktree.touched = True
        head = _replay(str(worktree.path), preview.result_commit)
        final_files = sorted(git(str(worktree.path), "diff", "--name-only", preview.target_head, head).stdout.split())
        final_diff = git(str(worktree.path), "diff", preview.target_head, head).stdout
        final_stat = git(str(worktree.path), "diff", "--stat", preview.target_head, head).stdout.strip()
        changed = _patch_id(repo_root, preview.base_commit, preview.result_commit) != _patch_id(
            str(worktree.path), preview.target_head, head)
        executor = executor_factory(Path(worktree.path), tuple(f for f in final_files if "test" in f))
        executor.run_all(checks)
        results = [{"check": e.check.description, "kind": e.check.kind.value, "status": e.result.status.value,
                    "output": e.result.output[-2000:]} for e in executor.executed]
        state = workspace.finalize(worktree, discard=False)
        return IntegrationOutcome("integrated", "", worktree.branch, str(worktree.path), head, final_files, final_diff,
                                  final_stat, changed, results, dict(state))
    except IntegrationRefused as exc:
        state = workspace.finalize(worktree, discard=not worktree.touched)
        return IntegrationOutcome("blocked", str(exc), worktree.branch, str(worktree.path), worktree_state=dict(state))
