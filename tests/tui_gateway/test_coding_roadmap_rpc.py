"""``coding.roadmap.*`` / ``coding.memory.*`` / ``coding.semantic.status`` through the validated
JSON-RPC dispatcher: strict params, single-milestone approvals, refusals as 5072."""

import pytest

from tests.meu_coding.phase3_support import make_git_repo
from tests.meu_coding.phase7_support import GOAL, ROADMAP, ScriptedPlanner, planner_service
from tui_gateway import server


def _call(method, params):
    return server.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def _ok(method, params):
    result = _call(method, params)
    assert "error" not in result, result
    return result["result"]


@pytest.fixture
def rpc(tmp_path, monkeypatch):
    repo = make_git_repo(tmp_path)
    service = planner_service(tmp_path, ScriptedPlanner(ROADMAP))
    monkeypatch.setattr(server, "_coding_service", lambda: service)
    return repo, service


def test_roadmap_flow_over_rpc(rpc):
    repo, _service = rpc
    roadmap = _ok("coding.roadmap.create", {"goal": GOAL, "project_root": str(repo)})["roadmap"]
    assert roadmap["actions"]["approve"] == ["m1"]
    m1 = roadmap["milestones"][0]
    params = {"roadmap_id": roadmap["roadmap_id"], "milestone_id": "m1", "fingerprint": m1["fingerprint"],
              "revision": roadmap["revision"], "confirmed": True}
    wrong = _call("coding.roadmap.approve", {**params, "milestone_id": "m2",
                                             "fingerprint": roadmap["milestones"][1]["fingerprint"]})
    assert wrong["error"]["code"] == 5072 and "not ready" in wrong["error"]["message"]
    started = _ok("coding.roadmap.approve", params)["roadmap"]
    assert started["milestones"][0]["status"] == "IN_PROGRESS"
    replay = _call("coding.roadmap.approve", params)
    assert replay["error"]["code"] == 5072
    listed = _ok("coding.roadmap.list", {})["roadmaps"]
    assert listed[0]["roadmap_id"] == roadmap["roadmap_id"] and listed[0]["counts"]["IN_PROGRESS"] == 1
    task = _ok("coding.get", {"task_id": started["milestones"][0]["task_id"]})["task"]
    assert task["roadmap"]["milestone"] == "m1" and task["relevance"]
    assert task["intelligence"]["ranking"]["items"] >= 1 and task["intelligence"]["semantic"]["status"] == "off"
    assert _ok("coding.semantic.status", {"project_root": str(repo)})["semantic"]["status"] == "off"


def test_roadmap_params_are_strict(rpc):
    repo, _ = rpc
    roadmap = _ok("coding.roadmap.create", {"goal": GOAL, "project_root": str(repo)})["roadmap"]
    rid = roadmap["roadmap_id"]
    bad = [
        ("coding.roadmap.approve", {"roadmap_id": rid, "milestone_id": "m1", "fingerprint": "x", "revision": 1,
                                    "confirmed": True}),
        ("coding.roadmap.approve", {"roadmap_id": rid, "milestone_id": "m1", "fingerprint": "0" * 64,
                                    "revision": 1}),
        ("coding.roadmap.approve", {"roadmap_id": rid, "milestone_id": "m1", "fingerprint": "0" * 64,
                                    "revision": 1, "confirmed": True, "all": True}),
        ("coding.roadmap.approve", {"roadmap_id": rid, "milestone_ids": ["m1", "m2"], "fingerprint": "0" * 64,
                                    "revision": 1, "confirmed": True}),
        ("coding.roadmap.revision", {"roadmap_id": rid, "revision_id": "0" * 16, "decision": "maybe"}),
        ("coding.memory.decide", {"task_id": "t", "candidate_id": "short", "decision": "accept"}),
        ("coding.roadmap.create", {"goal": "", "project_root": str(repo)}),
    ]
    for method, params in bad:
        assert "error" in _call(method, params), (method, params)
