"""Remote operations of ``CodingTaskService`` (a mixin): push, PR creation, PR monitoring, merge.

Starts from an INTEGRATED task (validated integration branch, final-diff Reviewer PASS).
Each mutation is a preview → an explicit approval naming that preview's fingerprint (with a
confirmation) → a re-verified execution. The three approvals are independent objects: a push
approval cannot create a PR, a PR approval cannot merge. Approvals are single use, consumed
under the task lock before anything is sent. Nothing here runs on a timer, deletes a branch,
force-pushes, or edits code from review comments (feedback becomes a NEW task the user starts).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from meu_coding import remote_ops
from meu_coding.github_adapter import GitHubError
from meu_coding.remote_refs import RemoteInfo, RemoteRefused, detect_remote

logger = logging.getLogger(__name__)
KINDS = ("push", "pr", "merge")
MAX_FEEDBACK_COMMENTS = 20


def _approval_source(source: str) -> str:
    if source == "desktop" or (source.startswith("phone-") and len(source) <= 80):
        return source
    raise RemoteRefused("Remote approvals come only from the desktop or a paired phone.")


class RemoteMixin:
    # ── shared helpers ──────────────────────────────────────────────────────

    def _remote_state(self, record) -> dict[str, Any]:
        if record.remote is None:
            record.remote = {"events": []}
        return record.remote

    def _remote_event(self, record, event: str, **fields: Any) -> None:
        remote = self._remote_state(record)
        entry = {"event": event, "at": round(time.time(), 3), **fields}
        remote["events"].append(entry)
        record.audit.remote = {k: v for k, v in remote.items() if k != "pending"}
        self._save(record)

    def _remote_info(self, record) -> RemoteInfo:
        info = detect_remote(record.project_root, github=self._github(), identity=self.remote_identity,
                             auth_available=self.remote_auth)
        self._remote_state(record)["info"] = info.to_dict()
        return info

    def _github(self):
        if getattr(self, "_github_client", None) is None:
            self._github_client = self.github_factory()
        return self._github_client

    def _require_integrated(self, record) -> None:
        from meu_coding.task_service import Stage, TaskError

        if record.stage != Stage.INTEGRATED or record.result is None or not record.integration.get("branch"):
            raise TaskError("Remote actions are available after a validated integration.")
        if (record.integration.get("review") or {}).get("verdict") != "pass":
            raise TaskError("The final integration diff has no Reviewer PASS — remote actions are unavailable.")

    def _facts(self, record) -> dict[str, Any]:
        integration = record.integration
        return {"changed_files": list(integration.get("final_files") or record.result.changed_files),
                "tests": [dict(c) for c in integration.get("checks") or []],
                "reviewer": (integration.get("review") or {}).get("verdict", ""),
                "risk": (record.pr or {}).get("risk") or "unknown"}

    def _remote_call(self, record, kind: str, fn):
        """Run one remote step; refusals and API errors become actionable task errors."""
        from meu_coding.task_service import TaskError

        started = time.perf_counter()
        try:
            return fn()
        except RemoteRefused as exc:
            raise TaskError(str(exc)) from None
        except GitHubError as exc:
            self._remote_event(record, f"{kind}_error", status=exc.status)
            raise TaskError(f"GitHub refused the request: {exc}") from None
        finally:
            record.timings[f"remote_{kind}"] = round(time.perf_counter() - started, 4)

    # ── read-only ───────────────────────────────────────────────────────────

    def remote_detect(self, task_id: str) -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            self._remote_call(record, "detect", lambda: self._remote_info(record))
            self._save(record)
        return self.get(task_id)

    # ── previews (read-only; replace any earlier preview of the same kind) ───

    def remote_preview(self, task_id: str, kind: str, *, title: str | None = None, body: str | None = None,
                       method: str = "squash") -> dict[str, Any]:
        from meu_coding.task_service import TaskError

        if kind not in KINDS:
            raise TaskError("Unknown remote action.")
        record = self._require(task_id)
        with record.lock:
            self._require_integrated(record)
            builder = {"push": self._push_preview, "pr": self._pr_preview, "merge": self._merge_preview}[kind]
            preview = self._remote_call(record, f"{kind}_preview",
                                        lambda: builder(record, title=title, body=body, method=method))
            remote = self._remote_state(record)
            remote.pop("blocked", None)
            remote.setdefault("pending", {})[kind] = preview
            remote[f"{kind}_preview"] = preview.to_dict()
            self._remote_event(record, f"{kind}_preview", fingerprint=preview.fingerprint)
        return self.get(task_id)

    def _push_preview(self, record, **_: Any):
        info = self._remote_info(record)
        return remote_ops.push_preview(repo=record.project_root, info=info, source_branch=record.integration["branch"],
                                       target_branch=record.result.target_branch, **self._facts(record))

    def _pr_preview(self, record, *, title: str | None, body: str | None, **_: Any):
        from meu_coding.task_service import TaskError

        remote = self._remote_state(record)
        if not remote.get("pushed"):
            raise TaskError("Push the integration branch first (its own approval).")
        if remote.get("pr"):
            raise TaskError("A pull request was already created for this task.")
        info = self._remote_info(record)
        local = record.pr or self._default_pr_text(record)
        return remote_ops.pr_preview(repo=record.project_root, info=info, pushed=remote["pushed"],
                                     target_branch=record.result.target_branch,
                                     title=title if title is not None else local.get("title", ""),
                                     body=body if body is not None else local.get("body", ""), **self._facts(record))

    def _default_pr_text(self, record) -> dict[str, Any]:
        from meu_coding.pr_preview import build_pr_preview

        plan = record.session.planning.plan if record.session and record.session.planning else None
        return build_pr_preview(description=record.task.description, plan_summary=plan.summary if plan else "",
                                risk=plan.risk.value if plan else "unknown", result=record.result.to_dict(),
                                integration=record.integration, reviewer=record.integration.get("review", {}),
                                remotes=[])

    def _merge_preview(self, record, *, method: str, **_: Any):
        from meu_coding.task_service import TaskError

        remote = self._remote_state(record)
        if not remote.get("pr"):
            raise TaskError("Create the pull request first (its own approval).")
        if remote.get("merged"):
            raise TaskError("This pull request was already merged.")
        info = self._remote_info(record)
        facts = self._facts(record)
        return remote_ops.merge_preview(info=info, github=self._github(), pr=remote["pr"],
                                        reviewed_target_sha=remote["pr_preview"]["target_sha"], method=str(method),
                                        changed_files=facts["changed_files"], reviewer=facts["reviewer"],
                                        risk=facts["risk"])

    def remote_cancel(self, task_id: str, kind: str, source: str = "desktop") -> dict[str, Any]:
        record = self._require(task_id)
        with record.lock:
            remote = self._remote_state(record)
            if (remote.get("pending") or {}).pop(kind, None) is not None:
                remote.pop(f"{kind}_preview", None)
                self._remote_event(record, f"{kind}_cancel", source=source)
        return self.get(task_id)

    # ── approvals (one per operation, single use) ───────────────────────────

    def remote_approve(self, task_id: str, kind: str, *, fingerprint: str, confirmed: bool,
                       source: str = "desktop") -> dict[str, Any]:
        from meu_coding.task_service import TaskError

        record = self._require(task_id)
        with record.lock:
            source = self._remote_call(record, "approve", lambda: _approval_source(str(source)))
            self._require_integrated(record)
            if kind not in KINDS:
                raise TaskError("Unknown remote action.")
            if confirmed is not True:
                raise TaskError("Remote action not confirmed.")
            pending = (self._remote_state(record).get("pending") or {}).get(kind)
            if pending is None:
                raise TaskError("This approval was already used or there is no preview — preview again.")
            if fingerprint != pending.fingerprint:
                raise TaskError("The preview changed after approval — preview again and approve the new one.")
            del record.remote["pending"][kind]  # consumed before anything is sent
            self._remote_event(record, f"{kind}_approved", source=source, fingerprint=pending.fingerprint)
            run = {"push": self._run_push, "pr": self._run_pr, "merge": self._run_merge}[kind]
            try:
                self._remote_call(record, kind, lambda: run(record, pending, source))
            except TaskError as exc:
                record.remote["blocked"] = {"kind": kind, "reason": str(exc)[:300], "at": round(time.time(), 3)}
                self._remote_event(record, f"{kind}_blocked", reason=str(exc)[:300])
                raise
        return self.get(task_id)

    def _run_push(self, record, preview, source: str) -> None:
        info = self._remote_info(record)
        pushed = remote_ops.execute_push(preview, repo=record.project_root, info=info)
        remote = record.remote
        remote["pushed"] = {**pushed, "source_commit": preview.source_commit, "refspec": preview.refspec,
                            "expected_remote_sha": preview.expected_remote_sha, "approved_by": source,
                            "at": round(time.time(), 3)}
        remote.pop("blocked", None)
        self._remote_event(record, "pushed", remote_sha=pushed["remote_sha"], branch=pushed["destination_branch"])

    def _run_pr(self, record, preview, source: str) -> None:
        info = self._remote_info(record)
        created = remote_ops.execute_pr(preview, repo=record.project_root, info=info, github=self._github())
        record.remote["pr"] = {**created, "approved_by": source}
        record.remote.pop("blocked", None)
        self._remote_event(record, "pr_created", number=created["number"], url=created["url"],
                           source_sha=created["source_sha"])

    def _run_merge(self, record, preview, source: str) -> None:
        info = self._remote_info(record)
        remote = record.remote
        facts = self._facts(record)
        merged = remote_ops.execute_merge(preview, repo=record.project_root, info=info, github=self._github(), pr=remote["pr"],
                                          reviewed_target_sha=remote["pr_preview"]["target_sha"],
                                          changed_files=facts["changed_files"], reviewer=facts["reviewer"],
                                          risk=facts["risk"])
        remote["merged"] = {**merged, "approved_by": source, "at": round(time.time(), 3)}
        remote.pop("blocked", None)
        self._remote_event(record, "merged", merge_commit=merged["merge_commit_sha"], method=merged["method"],
                           target_verified=merged["target_verified"])

    # ── monitoring (on demand) ──────────────────────────────────────────────

    def remote_refresh(self, task_id: str) -> dict[str, Any]:
        from meu_coding.task_service import TaskError

        record = self._require(task_id)
        with record.lock:
            remote = self._remote_state(record)
            if not remote.get("pr"):
                raise TaskError("There is no pull request to refresh.")
            info = self._remote_info(record)
            status = self._remote_call(record, "pr_refresh", lambda: remote_ops.pr_status(
                info=info, github=self._github(), pr=remote["pr"],
                reviewed_target_sha=remote["pr_preview"]["target_sha"]))
            remote["pr_status"] = {**status, "refreshed_at": round(time.time(), 3)}
            self._remote_event(record, "pr_refreshed", state=status["state"], checks=status["checks"]["state"],
                               head_drift=status["head_drift"], target_drift=status["target_drift"])
        return self.get(task_id)

    # ── PR feedback → a new task (never an automatic edit) ──────────────────

    def remote_feedback(self, task_id: str) -> list[dict[str, Any]]:
        from meu_coding.task_service import TaskError

        record = self._require(task_id)
        with record.lock:
            remote = self._remote_state(record)
            if not remote.get("pr"):
                raise TaskError("There is no pull request to read feedback from.")
            info = self._remote_info(record)
            number = int(remote["pr"]["number"])
            comments = self._remote_call(record, "feedback", lambda: self._github().review_comments(
                info.owner, info.repo, number))
        return [{"id": c.get("id"), "path": c.get("path", ""), "line": c.get("line"),
                 "author": (c.get("user") or {}).get("login", ""), "body": str(c.get("body", ""))[:2000]}
                for c in comments[:100]]

    def remote_repair_task(self, task_id: str, comment_ids: list[int]) -> dict[str, Any]:
        from meu_coding.task_service import TaskError

        chosen = {int(i) for i in comment_ids}
        if not chosen or len(chosen) > MAX_FEEDBACK_COMMENTS:
            raise TaskError(f"Select between 1 and {MAX_FEEDBACK_COMMENTS} review comments.")
        record = self._require(task_id)
        comments = [c for c in self.remote_feedback(task_id) if c["id"] in chosen]
        if len(comments) != len(chosen):
            raise TaskError("Some selected comments are no longer on the pull request — refresh and select again.")
        lines = [f"Address review feedback on PR #{record.remote['pr']['number']} ({record.task.description[:120]}):"]
        lines += [f"- {c['path']}:{c['line'] or '?'} ({c['author']}): {' '.join(c['body'].split())[:500]}"
                  for c in comments]
        files = tuple(sorted({c["path"] for c in comments if c["path"]}))
        view = self.start("\n".join(lines), record.project_root, explicit_files=files)
        with record.lock:
            self._remote_event(record, "repair_task_created", new_task=view["task_id"],
                               comments=sorted(chosen))
        return view
