"""A reproduced review finding repairs only its deliverable and keeps its folder."""

import json

from tests.plugins.delegation.test_meu_coordinator import task
from tests.plugins.delegation.test_meu_projects import create, project


def test_ready_work_prioritizes_an_unblocked_prerequisite(coordinator, tmp_path):
    _, built, parent = coordinator
    created = create(parent, tmp_path, [
        task(id="background-one"), task(id="background-two"),
        task("complex", ["app.js"], id="implement"),
        task(id="review", depends_on=["implement"], review_of="implement"),
    ])
    assert created["ready"] == ["implement", "background-one"]
    project(parent, "run")
    assert [entry["model"] for entry in built] == ["deepseek-v4-pro", "deepseek-flash"]


def test_review_reopens_only_its_deliverable_and_rechecks_the_repair(coordinator, tmp_path, monkeypatch):
    from tools import delegate_tool

    _, built, parent = coordinator
    root = tmp_path / "Meu Tasks #1"
    root.mkdir()
    app = root / "app.js"
    initial = create(parent, root, [
        task(paths=["app.js"], id="merge", goal="Implement the task merge."),
        task(id="inspect", goal="Inspect the other project files."),
        task(id="review", depends_on=["merge"], review_of="merge", goal="Check the task merge."),
    ])
    assert initial["project_folder_url"] == root.as_uri()
    assert "%20" in initial["project_folder_url"] and "%23" in initial["project_folder_url"]
    native_fixture_run = delegate_tool._run_single_child

    def run(*args, **kwargs):
        result = native_fixture_run(*args, **kwargs)
        child = kwargs["child"]
        if kwargs["goal"] == "Check the task merge.":
            broken = "Object.prototype" in app.read_text(encoding="utf-8")
            result.update(schema_valid=True, summary=json.dumps({
                "verdict": "needs_fix" if broken else "pass",
                "check": "Import a task with id constructor.",
                "observed": "The task was dropped." if broken else "The imported task was retained.",
            }))
            assert child._delegate_project_write_paths == ()
        return result

    monkeypatch.setattr(delegate_tool, "_run_single_child", run)
    project(parent, "run")
    app.write_text("if (t.id in Object.prototype || seen.has(t.id)) continue;", encoding="utf-8")
    project(parent, "verify", task="inspect", attempt=1, passed=True, evidence="Other files checked.")
    project(parent, "verify", task="merge", attempt=1, passed=True, evidence="Basic merge checked.", artifacts=["app.js"])
    project(parent, "run")
    assert "pass verdict" in project(parent, "verify", task="review", attempt=1, passed=True, evidence="Check.")["error"]
    assert "exact task attempt" in project(parent, "request_fix", task="review", attempt=2, evidence="Reproduced.")["error"]
    assert "evidence" in project(parent, "request_fix", task="review", attempt=1)["error"]

    queued = project(parent, "request_fix", task="review", attempt=1,
                     evidence="Reproduced the dropped constructor id in app.js.")
    assert queued["ready"] == ["merge"]
    assert queued["tasks"]["inspect"]["state"] == "verified"
    assert queued["tasks"]["inspect"]["attempt"] == 1
    assert queued["tasks"]["review"]["state"] == "pending"
    project(parent, "run")
    assert "The task was dropped." in built[-1]["context"]
    app.write_text("if (seen.has(t.id)) continue;", encoding="utf-8")
    project(parent, "verify", task="merge", attempt=2, passed=True, evidence="Constructor case passed.", artifacts=["app.js"])
    project(parent, "run")
    assert [entry["model"] for entry in built] == ["deepseek-flash", "deepseek-flash", "deepseek-v4-pro",
                                                   "deepseek-v4-pro", "deepseek-v4-pro"]
    assert built[-1]["allowed_tools"] == {"read_file", "write_file", "patch", "search_files"}
    final = project(parent, "verify", task="review", attempt=2, passed=True, evidence="Confirmed the review result.")
    assert final["complete"] and final["project_folder_url"] == initial["project_folder_url"]


def test_repair_refuses_a_review_after_the_artifact_changes_at_same_attempt(coordinator, tmp_path):
    _, _, parent = coordinator
    from tools import delegate_tool
    from unittest.mock import patch

    artifact = tmp_path / "report.txt"
    artifact.write_text("original", encoding="utf-8")
    create(parent, tmp_path, [task(paths=["report.txt"], id="write"),
                              task(id="review", depends_on=["write"], review_of="write")])
    project(parent, "run")
    project(parent, "verify", task="write", attempt=1, passed=True, evidence="Checked.", artifacts=["report.txt"])
    finding = json.dumps({"verdict": "needs_fix", "check": "Read the result.", "observed": "Missing detail."})
    with patch.object(delegate_tool, "_run_single_child", return_value={
        "task_index": 0, "status": "completed", "schema_valid": True, "summary": finding,
    }):
        project(parent, "run")
    artifact.write_text("changed", encoding="utf-8")
    project(parent, "verify", task="write", attempt=1, passed=True, evidence="Rechecked.", artifacts=["report.txt"])
    rejected = project(parent, "request_fix", task="review", attempt=1, evidence="Old issue.")
    assert "deliverable changed" in rejected["error"]
    assert project(parent, "status")["tasks"]["write"]["state"] == "verified"
