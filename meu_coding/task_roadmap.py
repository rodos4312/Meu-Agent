"""Roadmaps of ``CodingTaskService`` (a mixin): the AutonomousPlanner under user control.

Goal → (read-only, background) roadmap → the user approves ONE ready milestone at a time,
naming its fingerprint and the roadmap revision → that milestone becomes an ordinary coding
task (normal Architect / Coder / Reviewer / approval / isolated execution) → its outcome sets
the milestone status → the planner may PROPOSE a revision, which applies only if the user
accepts it. There is no "run until finished", no bulk approval and no self-approval.

Roadmaps are JSON files (MEU's atomic writer) and survive a restart. A restart never resumes
anything mutating: an interrupted milestone task shows as BLOCKED, and interrupted planning
(read-only) can simply be started again.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from meu_coding.autonomous_planner import (
    AutonomousPlanner,
    Milestone,
    MilestoneStatus,
    PlannerError,
    Roadmap,
    apply_revision,
    apply_user_edit,
    milestone_task_description,
    refresh_ready,
)

logger = logging.getLogger(__name__)
_ID = re.compile(r"^[0-9a-f]{32}$")
M = MilestoneStatus
DONE_STAGES = frozenset({"ready_to_commit", "committed", "integration_preview", "integrating", "integrated", "kept"})
BLOCKED_STAGES = frozenset({"blocked", "failed", "interrupted"})


def _source(source: str) -> str:
    if source == "desktop" or (source.startswith("phone-") and len(source) <= 80):
        return source
    raise PlannerError("Milestones are approved only from the desktop or a paired phone.")


class RoadmapMixin:
    # ── storage ─────────────────────────────────────────────────────────────

    def _roadmap_dir(self) -> Path:
        if self.audit_directory is not None:
            return Path(self.audit_directory).parent / "coding_roadmaps"
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()) / "coding_roadmaps"

    def _roadmaps(self) -> dict[str, Roadmap]:
        if getattr(self, "_roadmap_store", None) is None:
            self._roadmap_store = {}
            self._roadmap_lock = threading.RLock()
            self._load_roadmaps()
        return self._roadmap_store

    def _load_roadmaps(self) -> None:
        folder = self._roadmap_dir()
        if not folder.is_dir():
            return
        for path in sorted(folder.glob("*.json")):
            if not _ID.match(path.stem):
                continue
            try:
                roadmap = Roadmap.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("coding roadmap %s unreadable", path.name, exc_info=True)
                continue
            if roadmap.status == "planning":
                roadmap.status, roadmap.error = "planning_interrupted", "Meu restarted while planning; plan again."
            self._roadmap_store[roadmap.roadmap_id] = roadmap

    def _save_roadmap(self, roadmap: Roadmap) -> None:
        from tools.file_operations_native import atomic_write

        folder = self._roadmap_dir()
        folder.mkdir(parents=True, exist_ok=True)
        error = atomic_write(str(folder / f"{roadmap.roadmap_id}.json"),
                             json.dumps(roadmap.to_dict(), indent=1, sort_keys=True).encode("utf-8"))
        if error:
            roadmap.error = f"Roadmap could not be saved: {error}"

    def _roadmap(self, roadmap_id: str) -> Roadmap:
        roadmap = self._roadmaps().get(str(roadmap_id))
        if roadmap is None:
            raise PlannerError("No such roadmap.")
        return roadmap

    # ── planning (read-only, background) ────────────────────────────────────

    def roadmap_create(self, goal: str, project_root: str) -> dict[str, Any]:
        from meu_coding.workspace import WorkspaceError, read_identity

        if not " ".join(str(goal or "").split()):
            raise PlannerError("Describe the goal first.")
        try:
            root = read_identity(project_root).root
        except WorkspaceError:
            raise PlannerError("Choose a project folder that is a git repository with at least one commit.") from None
        import uuid

        roadmap = Roadmap(uuid.uuid4().hex, " ".join(goal.split())[:2000], root)
        roadmap.event("created")
        with self._lock_roadmaps():
            self._roadmaps()[roadmap.roadmap_id] = roadmap
            self._save_roadmap(roadmap)
        self.spawn(lambda: self._plan_roadmap(roadmap), f"coding-roadmap-{roadmap.roadmap_id[:8]}")
        return self.roadmap_get(roadmap.roadmap_id)

    def roadmap_replan(self, roadmap_id: str) -> dict[str, Any]:
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            if roadmap.status not in ("planning_interrupted", "failed"):
                raise PlannerError("Only an interrupted or failed plan can be planned again.")
            roadmap.status, roadmap.error = "planning", ""
            self._save_roadmap(roadmap)
        self.spawn(lambda: self._plan_roadmap(roadmap), f"coding-roadmap-{roadmap.roadmap_id[:8]}")
        return self.roadmap_get(roadmap_id)

    def _lock_roadmaps(self):
        self._roadmaps()
        return self._roadmap_lock

    def planner_context(self, project_root: str, goal: str) -> dict[str, Any]:
        """What the planner sees: ranked repository areas, project memory (stale marked) and
        deferred work. Reuses the cached index (changed files only), never a full rescan."""
        started = time.perf_counter()
        with self._root_lock(project_root):
            intel = self._intelligence(project_root)
            ranked = intel.rank(goal, limit=25)
            notes = self.memory.retrieve(project_root, goal, intel.analysis, intel.graph)
        return {"repository_areas": [{"path": r.path, "why": list(r.reasons[:3]), "score": r.score} for r in ranked],
                "memory": [n.to_dict() for n in notes if not n.stale],
                "stale_memory_ignored": [{"note": n.note, "why": n.stale_reason} for n in notes if n.stale],
                "deferred_work": [n.note for n in notes if n.category == "DEFERRED_WORK" and not n.stale],
                "files_indexed": len(intel.analysis.files_by_path),
                "seconds": round(time.perf_counter() - started, 3)}

    def _plan_roadmap(self, roadmap: Roadmap) -> None:
        try:
            context = self.planner_context(roadmap.project_root, roadmap.goal)
            planned = AutonomousPlanner(self.planner_factory()).plan(roadmap.goal, roadmap.project_root, context)
        except PlannerError as exc:
            self._planning_failed(roadmap, str(exc))
            return
        except Exception as exc:  # planning boundary: show a state, never a dead thread
            logger.warning("coding roadmap %s: planning failed", roadmap.roadmap_id, exc_info=True)
            self._planning_failed(roadmap, f"{type(exc).__name__}: {exc}")
            return
        with self._lock_roadmaps():
            roadmap.milestones, roadmap.revision, roadmap.status = planned.milestones, 1, "active"
            roadmap.context_summary = {"repository_areas": len(context["repository_areas"]),
                                       "memory_notes": len(context["memory"]),
                                       "stale_memory_ignored": len(context["stale_memory_ignored"]),
                                       "deferred_work": context["deferred_work"],
                                       "seconds": context["seconds"]}
            roadmap.event("planned", milestones=len(planned.milestones))
            self._save_roadmap(roadmap)

    def _planning_failed(self, roadmap: Roadmap, message: str) -> None:
        with self._lock_roadmaps():
            roadmap.status, roadmap.error = "failed", message[:500]
            roadmap.event("planning_failed")
            self._save_roadmap(roadmap)

    # ── reads (derive milestone status from its task; never start anything) ──

    def _sync(self, roadmap: Roadmap) -> bool:
        changed_ids = []
        for milestone in roadmap.milestones:
            if milestone.status != M.IN_PROGRESS.value or not milestone.task_id:
                continue
            record = self.tasks.get(milestone.task_id)
            stage = record.stage.value if record is not None else "missing"
            if stage in DONE_STAGES:
                milestone.status, milestone.outcome = M.DONE.value, f"task {stage}"
            elif stage in BLOCKED_STAGES or stage == "missing" or (record.restored and stage == "awaiting_approval"):
                milestone.status = M.BLOCKED.value
                milestone.outcome = f"task {stage} — nothing resumes automatically; decide on the task or reject"
            elif stage == "rejected":
                milestone.status, milestone.outcome = M.BLOCKED.value, "task rejected — reject or edit the milestone"
            else:
                continue
            changed_ids.append(milestone.id)
            roadmap.event("milestone_" + milestone.status.lower(), milestone=milestone.id, stage=stage)
        if changed_ids:
            refresh_ready(roadmap)
            self._save_roadmap(roadmap)
            done = [roadmap.milestone(i) for i in changed_ids if roadmap.milestone(i).status == M.DONE.value]
            if done and roadmap.status == "active" and roadmap.pending_revision is None:
                self.spawn(lambda: self._propose_revision(roadmap, done[-1]), f"coding-revise-{roadmap.roadmap_id[:8]}")
        return bool(changed_ids)

    def _propose_revision(self, roadmap: Roadmap, finished: Milestone) -> None:
        try:
            revision = AutonomousPlanner(self.planner_factory()).propose_revision(roadmap, finished)
        except PlannerError as exc:
            with self._lock_roadmaps():
                roadmap.event("revision_failed", reason=str(exc)[:200])
                self._save_roadmap(roadmap)
            return
        except Exception:  # a failed proposal leaves the roadmap as it is
            logger.warning("coding roadmap %s: revision failed", roadmap.roadmap_id, exc_info=True)
            return
        with self._lock_roadmaps():
            if revision is None:
                roadmap.event("revision_keep", after=finished.id)
            else:
                roadmap.pending_revision = revision
                roadmap.event("revision_proposed", revision=revision.revision_id, changes=revision.scope_expansion)
            self._save_roadmap(roadmap)

    def roadmap_get(self, roadmap_id: str) -> dict[str, Any]:
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            self._sync(roadmap)
            view = roadmap.to_dict()
        view["actions"] = {"approve": [m.id for m in roadmap.milestones if m.status == M.READY.value
                                       and roadmap.status == "active"],
                           "reject": [m.id for m in roadmap.milestones if m.status in (M.READY.value, M.PLANNED.value,
                                                                                       M.BLOCKED.value)],
                           "edit": roadmap.status in ("active", "paused"),
                           "pause": roadmap.status == "active", "resume": roadmap.status == "paused",
                           "replan": roadmap.status in ("planning_interrupted", "failed"),
                           "decide_revision": roadmap.pending_revision is not None}
        return view

    def roadmap_list(self) -> list[dict[str, Any]]:
        rows = []
        for roadmap in sorted(self._roadmaps().values(), key=lambda r: r.created_at, reverse=True):
            counts: dict[str, int] = {}
            for m in roadmap.milestones:
                counts[m.status] = counts.get(m.status, 0) + 1
            rows.append({"roadmap_id": roadmap.roadmap_id, "goal": roadmap.goal[:200], "status": roadmap.status,
                         "project": roadmap.project_root, "milestones": len(roadmap.milestones), "counts": counts,
                         "created_at": roadmap.created_at})
        return rows

    # ── user decisions ──────────────────────────────────────────────────────

    def milestone_approve(self, roadmap_id: str, milestone_id: str, *, fingerprint: str, revision: int,
                          confirmed: bool, source: str = "desktop") -> dict[str, Any]:
        """Approve exactly ONE ready milestone; it starts as a normal, separately approved task."""
        source = _source(str(source))
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            self._sync(roadmap)
            milestone = roadmap.milestone(milestone_id)
            if confirmed is not True:
                raise PlannerError("Milestone approval not confirmed.")
            if roadmap.status != "active":
                raise PlannerError(f"The roadmap is {roadmap.status}; milestones cannot be approved.")
            if milestone is None or revision != roadmap.revision or fingerprint != milestone.fingerprint:
                raise PlannerError("The roadmap or milestone changed after it was shown — review it again.")
            if milestone.status != M.READY.value:
                raise PlannerError("This milestone is not ready for approval (already approved, or waiting for "
                                   "its dependencies).")
            if any(m.status in (M.APPROVED.value, M.IN_PROGRESS.value) for m in roadmap.milestones):
                raise PlannerError("Another milestone of this roadmap is still in progress.")
            milestone.status = M.APPROVED.value  # consumed before the task starts
            roadmap.event("milestone_approved", milestone=milestone.id, source=source,
                          fingerprint=milestone.fingerprint)
            self._save_roadmap(roadmap)
        try:
            view = self._start_milestone(roadmap, milestone)
        except Exception as exc:
            with self._lock_roadmaps():
                milestone.status, milestone.outcome = M.BLOCKED.value, f"could not start: {str(exc)[:200]}"
                roadmap.event("milestone_blocked", milestone=milestone.id)
                self._save_roadmap(roadmap)
            raise
        with self._lock_roadmaps():
            milestone.status, milestone.task_id = M.IN_PROGRESS.value, view["task_id"]
            roadmap.event("milestone_started", milestone=milestone.id, task=view["task_id"])
            self._save_roadmap(roadmap)
        return self.roadmap_get(roadmap_id)

    def _start_milestone(self, roadmap: Roadmap, milestone: Milestone) -> dict[str, Any]:
        """Areas that are existing files were shown and approved with the milestone: they are the
        task's named files. Directories and missing paths stay discovery hints only."""
        from meu_coding.scope import is_protected, path_problem

        root = Path(roadmap.project_root)
        named = tuple(a for a in milestone.expected_areas
                      if path_problem(a) is None and not is_protected(a) and (root / a).is_file())
        hints = tuple((a, f"roadmap milestone {milestone.id}") for a in milestone.expected_areas if a not in named)
        return self.start(milestone_task_description(roadmap, milestone), roadmap.project_root, named,
                          context_hints=hints, milestone_kind=milestone.kind,
                          roadmap={"roadmap_id": roadmap.roadmap_id, "milestone": milestone.id})

    def milestone_reject(self, roadmap_id: str, milestone_id: str, source: str = "desktop") -> dict[str, Any]:
        source = _source(str(source))
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            milestone = roadmap.milestone(milestone_id)
            if milestone is None or milestone.status not in (M.READY.value, M.PLANNED.value, M.BLOCKED.value):
                raise PlannerError("Only a planned, ready or blocked milestone can be rejected.")
            milestone.status = M.REJECTED.value
            roadmap.event("milestone_rejected", milestone=milestone_id, source=source)
            refresh_ready(roadmap)
            self._save_roadmap(roadmap)
        return self.roadmap_get(roadmap_id)

    def roadmap_edit(self, roadmap_id: str, milestones: list[dict[str, Any]], *, revision: int,
                     source: str = "desktop") -> dict[str, Any]:
        source = _source(str(source))
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            if revision != roadmap.revision:
                raise PlannerError("The roadmap changed after it was shown — review it again.")
            if roadmap.status not in ("active", "paused"):
                raise PlannerError(f"The roadmap is {roadmap.status} and cannot be edited.")
            apply_user_edit(roadmap, milestones)
            roadmap.event("edited", source=source, revision=roadmap.revision)
            self._save_roadmap(roadmap)
        return self.roadmap_get(roadmap_id)

    def roadmap_revision_decide(self, roadmap_id: str, revision_id: str, *, accept: bool,
                                source: str = "desktop") -> dict[str, Any]:
        source = _source(str(source))
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            pending = roadmap.pending_revision
            if pending is None or pending.revision_id != revision_id:
                raise PlannerError("This revision proposal is no longer pending.")
            if accept:
                apply_revision(roadmap, pending)
            else:
                roadmap.pending_revision = None
            roadmap.event("revision_accepted" if accept else "revision_declined", revision=revision_id, source=source)
            self._save_roadmap(roadmap)
        return self.roadmap_get(roadmap_id)

    def roadmap_pause(self, roadmap_id: str, paused: bool, source: str = "desktop") -> dict[str, Any]:
        source = _source(str(source))
        roadmap = self._roadmap(roadmap_id)
        with self._lock_roadmaps():
            if paused and roadmap.status == "active":
                roadmap.status = "paused"
            elif not paused and roadmap.status == "paused":
                roadmap.status = "active"
            else:
                raise PlannerError(f"The roadmap is {roadmap.status}.")
            roadmap.event("paused" if paused else "resumed", source=source)
            self._save_roadmap(roadmap)
        return self.roadmap_get(roadmap_id)
