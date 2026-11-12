"""Phase 7 AutonomousPlanner: goal → milestone DAG; the user approves ONE ready milestone at a
time, which runs as an ordinary coding task; revisions are proposals; nothing runs on its own."""

import pytest

from meu_coding.autonomous_planner import (
    AutonomousPlanner,
    MilestoneStatus,
    PlannerError,
    Roadmap,
    apply_revision,
    topological_order,
    validate_milestones,
)
from meu_coding.task_service import Stage
from tests.meu_coding.phase3_support import git, make_git_repo
from tests.meu_coding.phase7_support import GOAL, ROADMAP, ScriptedPlanner, milestone, planner_service, roadmap_reply

M = MilestoneStatus


@pytest.fixture
def repo(tmp_path):
    return make_git_repo(tmp_path)


def _service(tmp_path, revisions=None):
    planner = ScriptedPlanner(ROADMAP, revisions)
    return planner_service(tmp_path, planner), planner


def _approve(service, view, mid, **over):
    m = next(x for x in view["milestones"] if x["id"] == mid)
    params = {"fingerprint": m["fingerprint"], "revision": view["revision"], "confirmed": True, "source": "desktop"}
    params.update(over)
    return service.milestone_approve(view["roadmap_id"], mid, **params)


def test_broad_goal_becomes_ordered_milestones_with_only_roots_ready(tmp_path, repo):
    service, planner = _service(tmp_path)
    view = service.roadmap_create(GOAL, str(repo))
    assert view["status"] == "active" and [m["id"] for m in view["milestones"]] == ["m1", "m2", "m3", "m4"]
    assert {m["id"]: m["status"] for m in view["milestones"]} == {"m1": "READY", "m2": "PLANNED", "m3": "PLANNED",
                                                                 "m4": "PLANNED"}
    assert view["actions"]["approve"] == ["m1"]
    context = planner.contexts[0]
    assert context["repository_areas"] and context["repository_areas"][0]["path"] == "calc/ops.py"
    assert any("97 pre-existing desktop" in d for d in context["deferred_work"]) is False  # repo has no register
    assert service.list() == []  # planning started no coding task


def test_dependencies_are_topologically_ordered_and_cycles_refused():
    ordered = validate_milestones([milestone("b", "B", ["a"]), milestone("a", "A")])
    assert [m.id for m in ordered] == ["a", "b"]
    with pytest.raises(PlannerError, match="cycle"):
        validate_milestones([milestone("a", "A", ["b"]), milestone("b", "B", ["a"])])
    with pytest.raises(PlannerError, match="unknown"):
        validate_milestones([milestone("a", "A", ["zz"])])
    with pytest.raises(PlannerError, match="itself"):
        topological_order(validate_milestones([milestone("a", "A")])[:0] + [validate_milestones(
            [milestone("a", "A")])[0].__class__("a", "A", "x", ["a"])])
    with pytest.raises(PlannerError, match="at most"):
        validate_milestones([milestone(f"m{i}", f"T{i}") for i in range(13)])


def test_milestone_needs_explicit_single_use_approval_and_starts_a_normal_task(tmp_path, repo):
    service, _ = _service(tmp_path)
    view = service.roadmap_create(GOAL, str(repo))
    head = git(repo, "rev-parse", "HEAD")
    with pytest.raises(PlannerError, match="not confirmed"):
        _approve(service, view, "m1", confirmed=False)
    with pytest.raises(PlannerError, match="changed after it was shown"):
        _approve(service, view, "m1", fingerprint="0" * 64)
    with pytest.raises(PlannerError, match="changed after it was shown"):
        _approve(service, view, "m1", revision=view["revision"] + 1)
    with pytest.raises(PlannerError, match="not ready"):
        _approve(service, view, "m2")
    started = _approve(service, view, "m1")
    m1 = next(m for m in started["milestones"] if m["id"] == "m1")
    assert m1["status"] == "IN_PROGRESS" and m1["task_id"]
    task = service.get(m1["task_id"])
    assert task["roadmap"] == {"roadmap_id": view["roadmap_id"], "milestone": "m1"}
    assert task["stage"] in ("awaiting_approval", "blocked", "failed")  # never executed without its own approval
    assert git(repo, "rev-parse", "HEAD") == head
    with pytest.raises(PlannerError, match="not ready"):
        _approve(service, view, "m1")  # replay


def test_planner_cannot_approve_its_own_milestones(tmp_path, repo):
    service, _ = _service(tmp_path)
    view = service.roadmap_create(GOAL, str(repo))
    for source in ("planner", "agent", "model", "auto"):
        with pytest.raises(PlannerError, match="desktop or a paired phone"):
            _approve(service, view, "m1", source=source)
    assert service.list() == []
    assert not hasattr(AutonomousPlanner(ScriptedPlanner(ROADMAP)), "approve")


def test_finished_milestone_unlocks_dependents_and_revision_is_only_a_proposal(tmp_path, repo):
    revision = {"reason": "split the state machine work",
                "operations": [{"op": "split", "milestone": "m2"}, {"op": "add", "milestone": "m2b"}],
                "milestones": [milestone("m1", "Analyze failures", areas=["calc/ops.py", "tests/test_ops.py"],
                                         kind="analysis"),
                               milestone("m2", "Improve state machine", ["m1"], ["calc/ops.py", "tests/test_ops.py"]),
                               milestone("m2b", "Harden reconnect path", ["m2"], ["net/"]),
                               milestone("m3", "Add regression tests", ["m2b"], ["tests/"], "tests"),
                               milestone("m4", "Final review", ["m2", "m3"], kind="review")]}
    service, _planner = _service(tmp_path, [revision])
    view = _approve(service, service.roadmap_create(GOAL, str(repo)), "m1")
    task_id = next(m for m in view["milestones"] if m["id"] == "m1")["task_id"]
    service.tasks[task_id].stage = Stage.COMMITTED  # the task finished through its own flow
    after = service.roadmap_get(view["roadmap_id"])
    statuses = {m["id"]: m["status"] for m in after["milestones"]}
    assert statuses["m1"] == "DONE" and statuses["m2"] == "READY"
    pending = after["pending_revision"]
    assert pending and pending["material"] and "new milestone m2b" in pending["scope_expansion"]
    assert "new area net/" in pending["scope_expansion"]
    assert [m["id"] for m in after["milestones"]] == ["m1", "m2", "m3", "m4"]  # not applied
    accepted = service.roadmap_revision_decide(view["roadmap_id"], pending["revision_id"], accept=True)
    assert [m["id"] for m in accepted["milestones"]] == ["m1", "m2", "m2b", "m3", "m4"]
    assert accepted["revision"] == view["revision"] + 1 and accepted["pending_revision"] is None


def test_revision_cannot_touch_finished_or_running_milestones(tmp_path):
    roadmap = AutonomousPlanner(ScriptedPlanner(ROADMAP)).plan("goal", "/p", {})
    roadmap.milestones[0].status = M.DONE.value
    bad = ScriptedPlanner(ROADMAP, [{"reason": "r", "operations": [{"op": "remove", "milestone": "m1"}],
                                     "milestones": [milestone("m2", "Improve state machine")]}])
    with pytest.raises(PlannerError, match="cannot be removed"):
        AutonomousPlanner(bad).propose_revision(roadmap, roadmap.milestones[0])


def test_stale_revision_is_refused():
    roadmap = AutonomousPlanner(ScriptedPlanner(ROADMAP)).plan("goal", "/p", {})
    planner = AutonomousPlanner(ScriptedPlanner(ROADMAP, [{"reason": "r", "operations": [{"op": "reorder"}],
                                                           "milestones": ROADMAP["milestones"]}]))
    revision = planner.propose_revision(roadmap, roadmap.milestones[0])
    roadmap.revision += 1
    with pytest.raises(PlannerError, match="out of date"):
        apply_revision(roadmap, revision)


def test_blocked_task_blocks_the_milestone_and_its_dependents_wait(tmp_path, repo):
    service, _ = _service(tmp_path)
    view = _approve(service, service.roadmap_create(GOAL, str(repo)), "m1")
    task_id = next(m for m in view["milestones"] if m["id"] == "m1")["task_id"]
    service.tasks[task_id].stage = Stage.BLOCKED
    after = service.roadmap_get(view["roadmap_id"])
    m1 = next(m for m in after["milestones"] if m["id"] == "m1")
    assert m1["status"] == "BLOCKED" and "nothing resumes automatically" in m1["outcome"]
    assert next(m for m in after["milestones"] if m["id"] == "m2")["status"] == "PLANNED"
    assert after["actions"]["approve"] == []


def test_no_parallel_milestones_and_pause_stops_approvals(tmp_path, repo):
    parallel = roadmap_reply(milestone("a", "Alpha"), milestone("b", "Beta"))
    service = planner_service(tmp_path, ScriptedPlanner(parallel))
    view = service.roadmap_create(GOAL, str(repo))
    assert sorted(view["actions"]["approve"]) == ["a", "b"]
    paused = service.roadmap_pause(view["roadmap_id"], True)
    with pytest.raises(PlannerError, match="paused"):
        _approve(service, paused, "a")
    resumed = service.roadmap_pause(view["roadmap_id"], False)
    started = _approve(service, resumed, "a")
    with pytest.raises(PlannerError, match="still in progress"):
        _approve(service, started, "b")


def test_user_edit_and_reject(tmp_path, repo):
    service, _ = _service(tmp_path)
    view = service.roadmap_create(GOAL, str(repo))
    edited = [dict(m, title=m["title"] + " (edited)") for m in view["milestones"] if m["id"] != "m4"]
    after = service.roadmap_edit(view["roadmap_id"], edited, revision=view["revision"])
    assert [m["id"] for m in after["milestones"]] == ["m1", "m2", "m3"] and after["revision"] == 2
    assert all(m["title"].endswith("(edited)") for m in after["milestones"])
    with pytest.raises(PlannerError, match="changed after it was shown"):
        service.roadmap_edit(view["roadmap_id"], edited, revision=view["revision"])
    rejected = service.milestone_reject(view["roadmap_id"], "m1")
    assert next(m for m in rejected["milestones"] if m["id"] == "m1")["status"] == "REJECTED"
    assert next(m for m in rejected["milestones"] if m["id"] == "m2")["note"].startswith("waiting for m1")


def test_roadmap_survives_restart_without_resuming_anything(tmp_path, repo):
    service, _ = _service(tmp_path)
    view = _approve(service, service.roadmap_create(GOAL, str(repo)), "m1")
    restored = planner_service(tmp_path, ScriptedPlanner(ROADMAP))
    again = restored.roadmap_get(view["roadmap_id"])
    assert again["goal"] == GOAL and again["revision"] == view["revision"]
    m1 = next(m for m in again["milestones"] if m["id"] == "m1")
    assert m1["status"] == "BLOCKED"  # its task's approval expired with the restart; nothing resumed
    assert restored.tasks[m1["task_id"]].restored


def test_interrupted_planning_is_marked_and_can_be_planned_again(tmp_path, repo):
    import json

    service, _ = _service(tmp_path)
    view = service.roadmap_create(GOAL, str(repo))
    path = tmp_path / "coding_roadmaps" / f"{view['roadmap_id']}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "planning"
    path.write_text(json.dumps(data), encoding="utf-8")
    restored = planner_service(tmp_path, ScriptedPlanner(ROADMAP))
    interrupted = restored.roadmap_get(view["roadmap_id"])
    assert interrupted["status"] == "planning_interrupted" and interrupted["actions"]["replan"]
    assert restored.roadmap_replan(view["roadmap_id"])["status"] == "active"


def test_invalid_planner_output_fails_cleanly(tmp_path, repo):
    service = planner_service(tmp_path, ScriptedPlanner({"milestones": [milestone("a", "A", ["a"])]}))
    view = service.roadmap_create(GOAL, str(repo))
    assert view["status"] == "failed" and "itself" in view["error"] and view["milestones"] == []


def test_roadmap_round_trips_through_json():
    roadmap = AutonomousPlanner(ScriptedPlanner(ROADMAP)).plan("goal", "/p", {})
    copy = Roadmap.from_dict(roadmap.to_dict())
    assert copy.fingerprint == roadmap.fingerprint and [m.fingerprint for m in copy.milestones] == \
        [m.fingerprint for m in roadmap.milestones]
