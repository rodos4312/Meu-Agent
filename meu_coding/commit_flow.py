"""Controlled local commit of a reviewed, kept worktree result.

Only reachable from READY_TO_COMMIT (approved → executed → tested → actual diff reviewed →
Reviewer PASS → user KEEP). The commit goes to the isolated worktree's own branch; the
parent checkout and its branch are never touched, nothing is merged or pushed, and no force
flag exists anywhere here.

``prepare_commit`` re-reads the worktree diff with MEU's ``working_diff`` and binds a token to
it; ``confirm_commit`` needs that token, an explicit ``confirmed=True`` and a user-supplied
message, and refuses if the worktree changed after review or after preparation. Git runs
through MEU's hardened, bounded runner (``bounded_probe_run`` + ``harden_git_argv`` +
``noninteractive_repo_git_env``: no hooks, pager, editor, credential helpers or filters).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from meu_coding.workspace import changed_files, diff_counts, git_probe, read_identity

GIT_TIMEOUT = 60.0
MAX_MESSAGE = 5_000


class CommitRefused(Exception):
    pass


@dataclass(frozen=True)
class CommitPlan:
    files: tuple[str, ...]
    stat: str
    additions: int
    deletions: int
    branch: str
    worktree_path: str
    base_commit: str
    parent_branch: str
    parent_head: str
    suggested_message: str
    token: str


def diff_digest(diff_text: str, files: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(files) + "\0" + diff_text).encode("utf-8")).hexdigest()


def suggest_message(task_description: str, files: tuple[str, ...], reviewer_rationale: str) -> str:
    """A suggestion only: the user accepts, edits or cancels it."""
    first = " ".join(task_description.strip().split())[:68] or "update"
    subject = f"feat(coding): {first[0].lower()}{first[1:]}"
    body = ["", "Files:", *(f"- {f}" for f in files), "", f"Review: {reviewer_rationale.strip()[:300]}"]
    return "\n".join([subject, *body]).strip() + "\n"


def _git(worktree: str, *args: str):
    from hermes_cli._subprocess_compat import bounded_probe_run, harden_git_argv, noninteractive_repo_git_env

    env = noninteractive_repo_git_env(worktree)
    if env is None:
        raise CommitRefused("Git filters in this repository could not be neutralised; commit refused.")
    result = bounded_probe_run(["git", "-C", worktree, *harden_git_argv(list(args))], timeout=GIT_TIMEOUT, env=env)
    if result is None:
        raise CommitRefused(f"git {args[0]} timed out or could not start")
    return result


def _read_diff(worktree: str) -> dict:
    from tools.working_diff import collect_working_diff

    diff = collect_working_diff(worktree, mode="all")
    if not diff.get("success"):
        raise CommitRefused(f"Could not read the worktree diff: {diff.get('error')}")
    return diff


def prepare_commit(*, worktree_path: str, worktree_branch: str, base_commit: str, parent_root: str,
                   reviewed_files: tuple[str, ...], reviewed_digest: str, task_description: str,
                   reviewer_rationale: str) -> CommitPlan:
    """``reviewed_digest`` is :func:`diff_digest` of the diff the Reviewer passed; the worktree
    must still produce exactly that diff (works after a restart, without keeping the diff)."""
    if not Path(worktree_path).is_dir():
        raise CommitRefused("The worktree no longer exists; nothing can be committed.")
    diff = _read_diff(worktree_path)
    files = changed_files(diff)
    current = diff_digest(diff.get("diff", ""), files)
    if files != tuple(sorted(reviewed_files)) or current != reviewed_digest:
        raise CommitRefused("The worktree changed after review — review it again before committing.")
    if git_probe(worktree_path, "rev-parse", "HEAD") != base_commit:
        raise CommitRefused("The worktree already has a commit; nothing more will be committed.")
    parent = read_identity(parent_root)
    additions, deletions = diff_counts(diff.get("diff", ""))
    return CommitPlan(
        files=files, stat=diff.get("stat", ""), additions=additions, deletions=deletions,
        branch=worktree_branch, worktree_path=worktree_path, base_commit=base_commit,
        parent_branch=parent.branch, parent_head=parent.head,
        suggested_message=suggest_message(task_description, files, reviewer_rationale),
        token=current,
    )


def _check_message(message: str) -> str:
    text = (message or "").strip()
    if not text:
        raise CommitRefused("Enter a commit message.")
    if len(text) > MAX_MESSAGE or "\x00" in text:
        raise CommitRefused("The commit message is too long or contains invalid characters.")
    return text + "\n"


def confirm_commit(plan: CommitPlan, *, message: str, token: str, confirmed: bool, parent_root: str) -> str:
    """Commit exactly the reviewed files on the worktree branch; returns the new commit hash."""
    if confirmed is not True:
        raise CommitRefused("Commit not confirmed.")
    if token != plan.token:
        raise CommitRefused("This commit preview is out of date — prepare the commit again.")
    text = _check_message(message)
    diff = _read_diff(plan.worktree_path)
    if diff_digest(diff.get("diff", ""), changed_files(diff)) != plan.token:
        raise CommitRefused("The worktree changed after the commit preview — prepare the commit again.")
    if git_probe(plan.worktree_path, "rev-parse", "--abbrev-ref", "HEAD") != plan.branch:
        raise CommitRefused("The worktree is no longer on its own branch; commit refused.")
    if not (git_probe(plan.worktree_path, "config", "user.name") and git_probe(plan.worktree_path, "config",
                                                                                "user.email")):
        raise CommitRefused("Set git user.name and user.email for this repository before committing.")
    added = _git(plan.worktree_path, "add", "--", *plan.files)
    if added.returncode != 0:
        raise CommitRefused(f"git add failed: {(added.stderr or '').strip()[:300]}")
    staged = git_probe(plan.worktree_path, "diff", "--cached", "--name-only")
    if tuple(sorted(staged.splitlines())) != plan.files:
        raise CommitRefused("The staged files differ from the reviewed files; commit refused.")
    committed = _commit(plan, text)
    if committed.returncode != 0:
        raise CommitRefused(f"git commit failed: {(committed.stderr or '').strip()[:300]}")
    head = git_probe(plan.worktree_path, "rev-parse", "HEAD")
    if git_probe(plan.worktree_path, "rev-parse", "HEAD^") != plan.base_commit:
        raise CommitRefused("Unexpected commit ancestry in the worktree; inspect it before continuing.")
    parent = read_identity(parent_root)
    if (parent.branch, parent.head) != (plan.parent_branch, plan.parent_head):
        raise CommitRefused("The parent checkout changed during the commit; inspect it before continuing.")
    return head


def _commit(plan: CommitPlan, message: str):
    from hermes_cli._subprocess_compat import bounded_probe_run, harden_git_argv, noninteractive_repo_git_env

    env = noninteractive_repo_git_env(plan.worktree_path)
    if env is None:
        raise CommitRefused("Git filters in this repository could not be neutralised; commit refused.")
    argv = ["git", "-C", plan.worktree_path, *harden_git_argv(["commit", "--quiet", "--file=-"])]
    result = bounded_probe_run(argv, timeout=GIT_TIMEOUT, env=env, input=message)
    if result is None:
        raise CommitRefused("git commit timed out or could not start")
    return result
