"""Remote operations: preview → one explicit approval → re-verified execution → verification.

Three independent operations, each with its own preview, fingerprint and approval:

- PUSH:  ``git push <remote> refs/heads/<src>:refs/heads/<dst>`` — fast-forward only, never
  ``--force``/``--force-with-lease``/``--mirror``/``--all``/``--tags``; the remote ref is
  re-read before the push (it must still be the previewed SHA) and after it (it must be the
  pushed SHA, else BLOCK).
- PR:    created through ``GitHubApi.create_pull`` only after its own approval, which binds the
  pushed head SHA, branches, exact title and body hash. No duplicate PR is ever opened.
- MERGE: through ``GitHubApi.merge`` with GitHub's ``sha`` guard, only after a NEW approval
  that binds the PR number, head SHA, target SHA, method and preview fingerprint.

Every name that reaches git or the API is validated (``meu_coding.remote_refs``); nothing is
built from model text. Branches are never deleted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from meu_coding.integration import git
from meu_coding.remote_refs import (
    FORBIDDEN_DESTINATIONS,
    PUSHABLE_PREFIXES,
    RemoteInfo,
    RemoteRefused,
    remote_branch_sha,
    validate_branch,
    validate_remote_name,
    validate_sha,
)

MAX_TITLE = 200
MAX_BODY = 20_000


def fingerprint(kind: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([kind, fields], sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _local_sha(repo: str, branch: str) -> str:
    out = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    return out.stdout.strip() if out.returncode == 0 else ""


def _is_ancestor(repo: str, old: str, new: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", old, new).returncode == 0


# ── push ─────────────────────────────────────────────────────────────────────


@dataclass
class PushPreview:
    repository: str
    remote: str
    remote_url: str
    source_branch: str
    source_commit: str
    destination_branch: str
    remote_exists: bool
    expected_remote_sha: str
    new_sha: str
    refspec: str
    force_required: bool
    target_branch: str
    changed_files: list[str]
    tests: list[dict[str, str]]
    reviewer: str
    risk: str
    status: str = "ready"  # "ready" | "blocked"
    reason: str = ""
    force: str = "FORBIDDEN"
    fingerprint: str = ""

    def bound(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("repository", "remote", "remote_url", "source_branch", "source_commit",
                                              "destination_branch", "expected_remote_sha", "new_sha", "refspec")}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _check_destination(info: RemoteInfo, destination: str, target_branch: str) -> None:
    if destination in FORBIDDEN_DESTINATIONS or destination in (info.default_branch, target_branch):
        raise RemoteRefused(f"Pushing to {destination} is not allowed — only the integration branch can be pushed.")
    if not destination.startswith(PUSHABLE_PREFIXES):
        raise RemoteRefused(f"Only integration branches ({', '.join(PUSHABLE_PREFIXES)}…) can be pushed.")


def push_preview(*, repo: str, info: RemoteInfo, source_branch: str, target_branch: str, changed_files: list[str],
                 tests: list[dict[str, str]], reviewer: str, risk: str) -> PushPreview:
    if not info.available:
        raise RemoteRefused(info.reason)
    remote = validate_remote_name(info.name)
    source = validate_branch(repo, source_branch)
    destination = source
    _check_destination(info, destination, target_branch)
    source_commit = _local_sha(repo, source)
    if not source_commit:
        raise RemoteRefused(f"The local branch {source} does not exist.")
    remote_sha = remote_branch_sha(repo, remote, destination)
    force = bool(remote_sha) and not _is_ancestor(repo, remote_sha, source_commit)
    preview = PushPreview(info.identity, remote, info.url, source, source_commit, destination, bool(remote_sha),
                          remote_sha, source_commit, f"refs/heads/{source}:refs/heads/{destination}", force,
                          target_branch, sorted(changed_files), tests, reviewer, risk)
    if force:
        preview.status, preview.reason = "blocked", "The remote branch has commits that are not in the local branch; "\
            "a force push would be required and is forbidden."
    elif remote_sha == source_commit:
        preview.status, preview.reason = "blocked", "The remote branch already has this commit."
    preview.fingerprint = fingerprint("push", preview.bound())
    return preview


def execute_push(preview: PushPreview, *, repo: str, info: RemoteInfo) -> dict[str, Any]:
    """Re-verify every bound fact, push fast-forward only, then verify the remote ref."""
    if preview.status != "ready":
        raise RemoteRefused(preview.reason or "This push is blocked.")
    fresh = push_preview(repo=repo, info=info, source_branch=preview.source_branch,
                         target_branch=preview.target_branch, changed_files=preview.changed_files,
                         tests=preview.tests, reviewer=preview.reviewer, risk=preview.risk)
    if fresh.fingerprint != preview.fingerprint:
        raise RemoteRefused("The repository, remote, branch or commits changed since the push preview — "
                            "preview the push again.")
    validate_sha(preview.new_sha)
    out = git(repo, "push", "--porcelain", "--no-verify", preview.remote, preview.refspec)
    if out.returncode != 0:
        raise RemoteRefused(f"git push failed: {out.stderr.strip()[:300]}")
    after = remote_branch_sha(repo, preview.remote, preview.destination_branch)
    if after != preview.new_sha:
        raise RemoteRefused(f"After the push the remote branch is {after[:12] or 'missing'}, "
                            f"not {preview.new_sha[:12]} — blocked.")
    return {"remote_sha": after, "destination_branch": preview.destination_branch, "remote": preview.remote}


# ── pull request ─────────────────────────────────────────────────────────────


@dataclass
class PullRequestPreview:
    repository: str
    owner: str
    repo: str
    source_branch: str
    source_sha: str
    target_branch: str
    target_sha: str
    title: str
    body: str
    body_hash: str
    commits: list[str]
    changed_files: list[str]
    tests: list[dict[str, str]]
    reviewer: str
    risk: str
    limitations: list[str]
    fingerprint: str = ""

    def bound(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("repository", "source_branch", "source_sha", "target_branch", "title",
                                              "body_hash")}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(title: str, body: str) -> tuple[str, str]:
    title = " ".join(str(title or "").split())[:MAX_TITLE]
    body = str(body or "")[:MAX_BODY].replace("\x00", "")
    if not title:
        raise RemoteRefused("The pull request needs a title.")
    return title, body


def pr_preview(*, repo: str, info: RemoteInfo, pushed: dict[str, Any], target_branch: str, title: str, body: str,
               changed_files: list[str], tests: list[dict[str, str]], reviewer: str, risk: str) -> PullRequestPreview:
    if not info.available:
        raise RemoteRefused(info.reason)
    source = validate_branch(repo, pushed["destination_branch"])
    target = validate_branch(repo, target_branch)
    head = validate_sha(pushed["remote_sha"])
    if remote_branch_sha(repo, info.name, source) != head:
        raise RemoteRefused("The pushed branch no longer points at the pushed commit — push again.")
    target_sha = remote_branch_sha(repo, info.name, target)
    if not target_sha:
        raise RemoteRefused(f"The target branch {target} does not exist on the remote.")
    title, body = _clean_text(title, body)
    commits = [line for line in git(repo, "log", "--format=%h %s", f"{target_sha}..{head}").stdout.splitlines()
               if line.strip()] if _local_sha(repo, source) else []
    preview = PullRequestPreview(info.identity, info.owner, info.repo, source, head, target, target_sha, title, body,
                                 hashlib.sha256(body.encode("utf-8")).hexdigest(), commits[:50], sorted(changed_files),
                                 tests, reviewer, risk,
                                 ["Prepared by the Meu Coding Engine; review the diff on GitHub before merging."])
    preview.fingerprint = fingerprint("pr", preview.bound())
    return preview


def execute_pr(preview: PullRequestPreview, *, repo: str, info: RemoteInfo, github) -> dict[str, Any]:
    if remote_branch_sha(repo, info.name, preview.source_branch) != preview.source_sha:
        raise RemoteRefused("The source branch changed after the PR preview — prepare the PR again.")
    if fingerprint("pr", preview.bound()) != preview.fingerprint:
        raise RemoteRefused("The PR preview changed — approve it again.")
    if github.find_pull(info.owner, info.repo, preview.source_branch, preview.target_branch):
        raise RemoteRefused("A pull request for this branch is already open — no duplicate was created.")
    created = github.create_pull(info.owner, info.repo, title=preview.title, body=preview.body,
                                 head=preview.source_branch, base=preview.target_branch)
    head = (created.get("head") or {}).get("sha", "")
    if head != preview.source_sha:
        raise RemoteRefused("GitHub reports a different head commit for the new PR — inspect it before continuing.")
    return {"number": int(created["number"]), "url": created.get("html_url", ""), "id": created.get("id"),
            "source_sha": head, "target_branch": preview.target_branch, "created_at": created.get("created_at", ""),
            "author": (created.get("user") or {}).get("login", ""), "state": created.get("state", "")}


# ── monitoring (read-only) ───────────────────────────────────────────────────


def _checks_summary(raw: dict[str, Any]) -> dict[str, Any]:
    states = [s.get("state") for s in (raw.get("status") or {}).get("statuses", [])]
    runs = raw.get("check_runs") or []
    pending = sum(1 for s in states if s == "pending") + sum(1 for r in runs if r.get("status") != "completed")
    failed = sum(1 for s in states if s in ("failure", "error"))
    failed += sum(1 for r in runs if r.get("status") == "completed"
                  and r.get("conclusion") not in ("success", "neutral", "skipped"))
    total = len(states) + len(runs)
    state = "failing" if failed else "pending" if pending else "passing" if total else "none"
    return {"state": state, "total": total, "failed": failed, "pending": pending}


def _reviews_summary(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    latest: dict[str, str] = {}
    for review in reviews:
        user = (review.get("user") or {}).get("login", "")
        if review.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[user] = review["state"]
    return {"approvals": sum(1 for s in latest.values() if s == "APPROVED"),
            "changes_requested": sum(1 for s in latest.values() if s == "CHANGES_REQUESTED"),
            "reviewers": sorted(latest)}


def pr_status(*, info: RemoteInfo, github, pr: dict[str, Any], reviewed_target_sha: str) -> dict[str, Any]:
    number = int(pr["number"])
    live = github.pull(info.owner, info.repo, number)
    head = (live.get("head") or {}).get("sha", "")
    base_sha = (live.get("base") or {}).get("sha", "")
    checks = _checks_summary(github.checks(info.owner, info.repo, head)) if head else {"state": "none"}
    reviews = _reviews_summary(github.reviews(info.owner, info.repo, number))
    return {"number": number, "state": live.get("state", ""), "merged": bool(live.get("merged")),
            "draft": bool(live.get("draft")), "mergeable": live.get("mergeable"),
            "mergeable_state": live.get("mergeable_state", ""), "head_sha": head, "base_sha": base_sha,
            "head_drift": head != pr["source_sha"], "target_drift": bool(reviewed_target_sha) and base_sha !=
            reviewed_target_sha, "checks": checks, "reviews": reviews, "url": live.get("html_url", pr.get("url", ""))}


# ── merge ────────────────────────────────────────────────────────────────────


@dataclass
class MergePreview:
    repository: str
    pr_number: int
    source_sha: str
    target_branch: str
    target_sha: str
    method: str
    allowed_methods: list[str]
    checks: dict[str, Any]
    reviews: dict[str, Any]
    changed_files: list[str]
    diff_summary: str
    target_drift: bool
    conflicts: bool
    reviewer: str
    risk: str
    status: str  # "clean" | "revalidation_required" | "conflict" | "blocked"
    reasons: list[str] = field(default_factory=list)
    fingerprint: str = ""

    def bound(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("repository", "pr_number", "source_sha", "target_sha", "method")}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge_blockers(status: dict[str, Any], approved_head: str, method: str, allowed: list[str]) -> list[str]:
    reasons = []
    if status["state"] != "open" or status["merged"]:
        reasons.append("The pull request is not open.")
    if status["draft"]:
        reasons.append("The pull request is a draft.")
    if status["head_sha"] != approved_head:
        reasons.append("The PR head changed after it was reviewed — the new commits need review and approval.")
    if status["checks"]["state"] in ("failing", "pending"):
        reasons.append(f"Checks are {status['checks']['state']}.")
    if status["reviews"]["changes_requested"]:
        reasons.append("A reviewer requested changes.")
    if method not in allowed:
        reasons.append(f"The repository does not allow the {method} merge method.")
    return reasons


def merge_preview(*, info: RemoteInfo, github, pr: dict[str, Any], reviewed_target_sha: str, method: str,
                  changed_files: list[str], reviewer: str, risk: str) -> MergePreview:
    if not info.available:
        raise RemoteRefused(info.reason)
    status = pr_status(info=info, github=github, pr=pr, reviewed_target_sha=reviewed_target_sha)
    allowed = list(info.merge_methods)
    reasons = _merge_blockers(status, pr["source_sha"], method, allowed)
    conflict = status["mergeable"] is False or status["mergeable_state"] == "dirty"
    if conflict:
        state = "conflict"
    elif reasons or reviewer != "pass":
        state = "blocked"
        if reviewer != "pass":
            reasons.append("The Meu Reviewer has not passed the final diff.")
    elif status["target_drift"]:
        state, reasons = "revalidation_required", ["The target branch moved since review — revalidate before merging."]
    else:
        state = "clean"
    preview = MergePreview(info.identity, status["number"], status["head_sha"], pr["target_branch"],
                           status["base_sha"], method, allowed, status["checks"], status["reviews"],
                           sorted(changed_files), f"{len(changed_files)} file(s)", status["target_drift"], conflict,
                           reviewer, risk, state, reasons)
    preview.fingerprint = fingerprint("merge", preview.bound())
    return preview


def execute_merge(preview: MergePreview, *, repo: str, info: RemoteInfo, github, pr: dict[str, Any],
                  reviewed_target_sha: str, changed_files: list[str], reviewer: str, risk: str) -> dict[str, Any]:
    if preview.status != "clean":
        raise RemoteRefused("Merge is not available: " + "; ".join(preview.reasons or [preview.status]))
    fresh = merge_preview(info=info, github=github, pr=pr, reviewed_target_sha=reviewed_target_sha,
                          method=preview.method, changed_files=changed_files, reviewer=reviewer, risk=risk)
    if fresh.fingerprint != preview.fingerprint or fresh.status != "clean":
        raise RemoteRefused("The pull request, its head, the target branch or the checks changed since the merge "
                            "preview — preview the merge again.")
    result = github.merge(info.owner, info.repo, preview.pr_number, sha=preview.source_sha, method=preview.method)
    if not result.get("merged"):
        raise RemoteRefused(f"GitHub did not merge the pull request: {str(result.get('message', ''))[:200]}")
    after = github.pull(info.owner, info.repo, preview.pr_number)
    if not after.get("merged"):
        raise RemoteRefused("GitHub does not report the pull request as merged — inspect it.")
    merge_sha = result.get("sha") or after.get("merge_commit_sha", "")
    target_now = remote_branch_sha(repo, info.name, preview.target_branch)
    return {"merged": True, "merge_commit_sha": merge_sha, "source_sha": preview.source_sha,
            "target_branch": preview.target_branch, "target_before": preview.target_sha, "target_after": target_now,
            "target_verified": bool(merge_sha) and target_now == merge_sha, "method": preview.method,
            "pr_number": preview.pr_number}
