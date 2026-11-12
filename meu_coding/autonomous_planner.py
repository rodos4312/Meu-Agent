"""AutonomousPlanner: a broad goal → an ordered roadmap of milestones. It only PLANS.

The planner cannot approve its roadmap or a milestone, execute or edit files, push, open a PR,
merge or install anything; it has no handle to any of those (it receives text context and
returns validated data). Every milestone runs as an ordinary coding task (Architect → Coder →
Reviewer → approval → isolated execution) only after the user approves THAT milestone.

Milestones form a small task DAG (``depends_on``), unrelated to the code dependency graph;
cycles and unknown dependencies are rejected. After a milestone ends, the planner may PROPOSE a
revision (keep, reorder, split, add, remove). A proposal is data until the user accepts it; any
material change, and any new area of the repository it would touch, is shown first.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol

MAX_MILESTONES = 12
MAX_TEXT = 600
RISKS = ("low", "medium", "high")
COMPLEXITIES = ("simple", "complex")
KINDS = ("analysis", "design", "implementation", "tests", "ux", "migration", "security", "review", "docs")
REVISION_OPS = ("keep", "reorder", "split", "add", "remove")


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"
    REJECTED = "REJECTED"


SETTLED = frozenset({MilestoneStatus.DONE, MilestoneStatus.REJECTED})
LOCKED = frozenset({MilestoneStatus.APPROVED, MilestoneStatus.IN_PROGRESS, MilestoneStatus.DONE})


class PlannerError(Exception):
    """The planner's output is unusable; nothing is created or changed."""


@dataclass
class Milestone:
    id: str
    title: str
    objective: str
    depends_on: list[str] = field(default_factory=list)
    expected_areas: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    risk: str = "medium"
    complexity: str = "complex"
    kind: str = "implementation"
    status: str = MilestoneStatus.PLANNED.value
    task_id: str = ""
    outcome: str = ""
    note: str = ""

    def content(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("id", "title", "objective", "depends_on", "expected_areas",
                                               "acceptance_criteria", "tests", "risk", "complexity", "kind")}

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.content(), sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "fingerprint": self.fingerprint}


@dataclass
class RoadmapRevision:
    revision_id: str
    based_on: int
    reason: str
    operations: list[dict[str, Any]]
    milestones: list[Milestone]
    material: bool
    scope_expansion: list[str]
    created_at: float = field(default_factory=lambda: round(time.time(), 3))

    def to_dict(self) -> dict[str, Any]:
        return {"revision_id": self.revision_id, "based_on": self.based_on, "reason": self.reason,
                "operations": self.operations, "milestones": [m.to_dict() for m in self.milestones],
                "material": self.material, "scope_expansion": self.scope_expansion, "created_at": self.created_at}


@dataclass
class Roadmap:
    roadmap_id: str
    goal: str
    project_root: str
    milestones: list[Milestone] = field(default_factory=list)
    revision: int = 0
    status: str = "planning"  # planning | active | paused | done | failed | planning_interrupted
    error: str = ""
    created_at: float = field(default_factory=lambda: round(time.time(), 3))
    pending_revision: RoadmapRevision | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    context_summary: dict[str, Any] = field(default_factory=dict)

    def milestone(self, milestone_id: str) -> Milestone | None:
        return next((m for m in self.milestones if m.id == milestone_id), None)

    @property
    def fingerprint(self) -> str:
        body = [m.content() for m in self.milestones]
        return hashlib.sha256(json.dumps([self.goal, self.revision, body], sort_keys=True).encode()).hexdigest()

    def event(self, name: str, **fields: Any) -> None:
        self.events.append({"event": name, "at": round(time.time(), 3), **fields})

    def to_dict(self) -> dict[str, Any]:
        return {"roadmap_id": self.roadmap_id, "goal": self.goal, "project_root": self.project_root,
                "milestones": [m.to_dict() for m in self.milestones], "revision": self.revision,
                "status": self.status, "error": self.error, "created_at": self.created_at,
                "pending_revision": self.pending_revision.to_dict() if self.pending_revision else None,
                "events": self.events[-50:], "fingerprint": self.fingerprint,
                "context_summary": self.context_summary}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Roadmap:
        known = Milestone.__dataclass_fields__
        milestones = [Milestone(**{k: v for k, v in m.items() if k in known}) for m in data.get("milestones", [])]
        roadmap = cls(data["roadmap_id"], data["goal"], data["project_root"], milestones, int(data.get("revision", 0)),
                      data.get("status", "active"), data.get("error", ""), data.get("created_at", time.time()))
        roadmap.events = list(data.get("events", []))
        roadmap.context_summary = dict(data.get("context_summary", {}))
        pending = data.get("pending_revision")
        if pending:
            roadmap.pending_revision = RoadmapRevision(
                pending["revision_id"], pending["based_on"], pending["reason"], pending["operations"],
                [Milestone(**{k: v for k, v in m.items() if k in known}) for m in pending["milestones"]],
                pending["material"], pending["scope_expansion"], pending.get("created_at", time.time()))
        return roadmap


# ── validation ───────────────────────────────────────────────────────────────


def _text(value: Any, name: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise PlannerError(f"milestone {name} is empty")
    return text[:limit]


def _texts(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [" ".join(str(v).split())[:200] for v in value if str(v).strip()][:limit]


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    value = str(value or "").strip().lower()
    return value if value in allowed else default


def milestone_from(data: Mapping[str, Any]) -> Milestone:
    if not isinstance(data, Mapping):
        raise PlannerError("a milestone must be an object")
    mid = _text(data.get("id"), "id", 24)
    return Milestone(mid, _text(data.get("title"), "title", 120), _text(data.get("objective"), "objective"),
                     [str(d) for d in data.get("depends_on") or [] if str(d).strip()],
                     _texts(data.get("expected_areas")), _texts(data.get("acceptance_criteria")),
                     _texts(data.get("tests")), _choice(data.get("risk"), RISKS, "medium"),
                     _choice(data.get("complexity"), COMPLEXITIES, "complex"),
                     _choice(data.get("kind"), KINDS, "implementation"))


def topological_order(milestones: list[Milestone]) -> list[str]:
    """Raises on unknown dependencies or cycles (Kahn's algorithm; stable by list order)."""
    ids = [m.id for m in milestones]
    if len(set(ids)) != len(ids):
        raise PlannerError("milestone ids must be unique")
    known = set(ids)
    for m in milestones:
        unknown = [d for d in m.depends_on if d not in known]
        if unknown:
            raise PlannerError(f"{m.id} depends on unknown milestone(s) {unknown}")
        if m.id in m.depends_on:
            raise PlannerError(f"{m.id} depends on itself")
    remaining = {m.id: set(m.depends_on) for m in milestones}
    order: list[str] = []
    while remaining:
        ready = [i for i in ids if i in remaining and not remaining[i]]
        if not ready:
            raise PlannerError("milestone dependencies contain a cycle: " + ", ".join(sorted(remaining)))
        for i in ready:
            order.append(i)
            del remaining[i]
            for deps in remaining.values():
                deps.discard(i)
    return order


def validate_milestones(raw: Any) -> list[Milestone]:
    if not isinstance(raw, list) or not raw:
        raise PlannerError("the roadmap has no milestones")
    if len(raw) > MAX_MILESTONES:
        raise PlannerError(f"a roadmap has at most {MAX_MILESTONES} milestones")
    milestones = [milestone_from(m) for m in raw]
    order = topological_order(milestones)
    by_id = {m.id: m for m in milestones}
    return [by_id[i] for i in order]


def refresh_ready(roadmap: Roadmap) -> None:
    """PLANNED → READY once every dependency is DONE (never the other way for settled ones)."""
    status = {m.id: m.status for m in roadmap.milestones}
    for m in roadmap.milestones:
        if m.status in (MilestoneStatus.PLANNED.value, MilestoneStatus.READY.value):
            deps_done = all(status[d] == MilestoneStatus.DONE.value for d in m.depends_on)
            blocked = [d for d in m.depends_on if status[d] in (MilestoneStatus.REJECTED.value,
                                                                 MilestoneStatus.BLOCKED.value)]
            m.status = MilestoneStatus.READY.value if deps_done else MilestoneStatus.PLANNED.value
            m.note = f"waiting for {', '.join(blocked)} (blocked or rejected)" if blocked else ""
    if roadmap.milestones and all(m.status in {s.value for s in SETTLED} for m in roadmap.milestones):
        roadmap.status = "done"


# ── the planner ──────────────────────────────────────────────────────────────


class PlannerModel(Protocol):
    def propose_roadmap(self, goal: str, context: dict[str, Any]) -> dict[str, Any]: ...

    def propose_revision(self, roadmap: dict[str, Any], finished: dict[str, Any]) -> dict[str, Any]: ...


def _areas(milestones: list[Milestone]) -> set[str]:
    return {a for m in milestones for a in m.expected_areas}


class AutonomousPlanner:
    def __init__(self, model: PlannerModel) -> None:
        self.model = model

    def plan(self, goal: str, project_root: str, context: dict[str, Any]) -> Roadmap:
        goal = " ".join(goal.split())
        if not goal:
            raise PlannerError("Describe the goal first.")
        data = self.model.propose_roadmap(goal, context)
        milestones = validate_milestones(data.get("milestones") if isinstance(data, Mapping) else None)
        roadmap = Roadmap(uuid.uuid4().hex, goal, project_root, milestones, revision=1, status="active")
        refresh_ready(roadmap)
        roadmap.event("planned", milestones=len(milestones))
        return roadmap

    def propose_revision(self, roadmap: Roadmap, finished: Milestone) -> RoadmapRevision | None:
        """A PROPOSAL only. ``None`` when the planner keeps the roadmap unchanged."""
        data = self.model.propose_revision(roadmap.to_dict(), finished.to_dict())
        if not isinstance(data, Mapping):
            raise PlannerError("the revision must be an object")
        ops = [o for o in data.get("operations") or [] if isinstance(o, Mapping)]
        kinds = [str(o.get("op", "")).lower() for o in ops]
        if any(k not in REVISION_OPS for k in kinds):
            raise PlannerError(f"unknown revision operation in {kinds}")
        if not ops or set(kinds) == {"keep"}:
            return None
        proposed = validate_milestones(data.get("milestones"))
        _check_locked(roadmap, proposed)
        for m in proposed:
            current = roadmap.milestone(m.id)
            if current is not None and current.status in {s.value for s in LOCKED | SETTLED}:
                m.status, m.task_id, m.outcome = current.status, current.task_id, current.outcome
        expansion = sorted(_areas(proposed) - _areas(roadmap.milestones))
        new_ids = sorted({m.id for m in proposed} - {m.id for m in roadmap.milestones})
        notes = [f"new milestone {i}" for i in new_ids] + [f"new area {a}" for a in expansion]
        return RoadmapRevision(uuid.uuid4().hex[:16], roadmap.revision, _text(data.get("reason") or "revision", "reason"),
                               [{k: str(v)[:200] for k, v in o.items()} for o in ops], proposed, True, notes)


def _check_locked(roadmap: Roadmap, proposed: list[Milestone]) -> None:
    """Approved, running and finished milestones cannot be removed or rewritten by a revision."""
    by_id = {m.id: m for m in proposed}
    for current in roadmap.milestones:
        if current.status in {s.value for s in LOCKED} | {MilestoneStatus.REJECTED.value}:
            replacement = by_id.get(current.id)
            if replacement is None:
                raise PlannerError(f"{current.id} is {current.status} and cannot be removed")
            if replacement.content() != current.content():
                raise PlannerError(f"{current.id} is {current.status} and cannot be changed")


def apply_revision(roadmap: Roadmap, revision: RoadmapRevision) -> None:
    if revision.based_on != roadmap.revision:
        raise PlannerError("The roadmap changed after this revision was proposed — it is out of date.")
    _check_locked(roadmap, revision.milestones)
    topological_order(revision.milestones)
    roadmap.milestones = revision.milestones
    roadmap.revision += 1
    roadmap.pending_revision = None
    refresh_ready(roadmap)


def apply_user_edit(roadmap: Roadmap, raw: list[Mapping[str, Any]]) -> None:
    """The user's own edit of the roadmap (titles, objectives, order, removals, new milestones)."""
    proposed = validate_milestones(raw)
    _check_locked(roadmap, proposed)
    for m in proposed:
        current = roadmap.milestone(m.id)
        if current is not None:
            m.status, m.task_id, m.outcome = current.status, current.task_id, current.outcome
    roadmap.milestones = proposed
    roadmap.revision += 1
    roadmap.pending_revision = None
    refresh_ready(roadmap)


def milestone_task_description(roadmap: Roadmap, milestone: Milestone) -> str:
    lines = [f"{milestone.title}: {milestone.objective}"]
    if milestone.acceptance_criteria:
        lines.append("Acceptance criteria: " + "; ".join(milestone.acceptance_criteria))
    if milestone.tests:
        lines.append("Tests: " + "; ".join(milestone.tests))
    lines.append(f"(Milestone {milestone.id} of the roadmap: {roadmap.goal[:200]})")
    return "\n".join(lines)
