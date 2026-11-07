"""Real project dispatch enforces requirements before quality, with bounded repairs."""

import json

import pytest

from tests.plugins.delegation.test_meu_coordinator import task
from tests.plugins.delegation.test_meu_projects import create, project


@pytest.fixture
def findings(coordinator, monkeypatch):
    from tools import delegate_tool

    original = delegate_tool._run_single_child
    outcomes = {}

    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        for stage in ("requirements", "quality"):
            if kwargs["goal"].startswith(f"{stage.capitalize()} review:"):
                assert kwargs["child"]._delegate_project_write_paths == ()
                result.update(schema_valid=True, summary=json.dumps({
                    "verdict": outcomes.get(stage, "pass"),
                    "check": f"Inspect {stage} against the saved task and artifact.",
                    "observed": "A concrete check was performed on this version.",
                }))
        return result

    monkeypatch.setattr(delegate_tool, "_run_single_child", run)
    return outcomes


def stages(created, target="build"):
    return {row["task"]["review_stage"]: key for key, row in created["tasks"].items()
            if row["task"].get("review_of") == target and row["task"].get("review_stage")}


def accept(parent, key, *, attempt=1, artifacts=None):
    result = project(parent, "verify", task=key, attempt=attempt, passed=True,
                     evidence="Executed the recorded acceptance check on this version.", artifacts=artifacts or [])
    assert "error" not in result, result
    return result


def test_implementation_requires_both_ordered_reviews_before_dependent_work(coordinator, tmp_path, findings):
    _, built, parent = coordinator
    created = create(parent, tmp_path, [
        task("complex", ["app.py"], id="build", goal="Implement the requested application."),
        task(id="deliver", depends_on=["build"]),
    ])
    review = stages(created)
    assert set(review) == {"requirements", "quality"}
    project(parent, "run")
    (tmp_path / "app.py").write_text("print('working')", encoding="utf-8")
    checked = accept(parent, "build", artifacts=["app.py"])
    assert checked["ready"] == [review["requirements"]] and not checked["complete"]
    project(parent, "run")
    assert project(parent, "run")["ready"] == []  # completion is not accepted review
    assert len(built) == 2
    assert accept(parent, review["requirements"])["ready"] == [review["quality"]]
    project(parent, "run")
    assert accept(parent, review["quality"])["ready"] == ["deliver"]
    project(parent, "run")
    assert accept(parent, "deliver")["complete"]
    assert len(built) == 4
    for child in built[1:3]:
        assert child["allowed_tools"] == {"read_file", "write_file", "patch", "search_files"}
        assert child["model"] == "deepseek-v4-pro"
        assert child["routing_cfg"]["fallback_providers"] == []
    assert "Review stage: requirements" in built[1]["context"]
    assert "Review stage: quality" in built[2]["context"]


def test_quality_repair_restarts_requirements_and_keeps_unrelated_acceptance(coordinator, tmp_path, findings):
    _, built, parent = coordinator
    created = create(parent, tmp_path, [task("standard", ["app.py"], id="build"), task(id="unrelated")])
    review = stages(created)
    project(parent, "run")
    artifact = tmp_path / "app.py"
    artifact.write_text("broken", encoding="utf-8")
    accept(parent, "unrelated")
    accept(parent, "build", artifacts=["app.py"])
    project(parent, "run")
    accept(parent, review["requirements"])
    findings["quality"] = "needs_fix"
    project(parent, "run")
    refused = project(parent, "verify", task=review["quality"], attempt=1, passed=True, evidence="Checked.")
    assert "pass verdict" in refused["error"]
    fixed = project(parent, "request_fix", task=review["quality"], attempt=1,
                    evidence="Reproduced the quality failure in the current app.py.")
    assert fixed["ready"] == ["build"]
    assert all(fixed["tasks"][key]["state"] == "pending" for key in review.values())
    assert fixed["tasks"]["unrelated"]["state"] == "verified"
    project(parent, "run")
    artifact.write_text("repaired", encoding="utf-8")
    assert accept(parent, "build", attempt=2, artifacts=["app.py"])["ready"] == [review["requirements"]]
    project(parent, "run")
    assert accept(parent, review["requirements"], attempt=2)["ready"] == [review["quality"]]
    findings["quality"] = "pass"
    project(parent, "run")
    final = accept(parent, review["quality"], attempt=2)
    assert final["complete"]
    assert final["tasks"]["unrelated"]["attempt"] == 1
    assert len(built) == 7


def test_changed_artifact_cannot_reuse_either_review_even_at_same_attempt(coordinator, tmp_path, findings):
    _, _, parent = coordinator
    created = create(parent, tmp_path, [task("complex", ["app.py"], id="build")])
    review = stages(created)
    project(parent, "run")
    artifact = tmp_path / "app.py"
    artifact.write_text("version one", encoding="utf-8")
    accept(parent, "build", artifacts=["app.py"])
    project(parent, "run")
    accept(parent, review["requirements"])
    project(parent, "run")
    artifact.write_text("version two", encoding="utf-8")
    assert not project(parent, "status")["complete"]
    refreshed = accept(parent, "build", artifacts=["app.py"])
    assert refreshed["ready"] == [review["requirements"]]
    stale = project(parent, "verify", task=review["quality"], attempt=1, passed=True, evidence="Old result.")
    assert "error" in stale
    assert not project(parent, "status")["complete"]


@pytest.mark.parametrize("workload,paths", [("routine", ["app.py"]), ("complex", [])])
def test_light_or_read_only_work_does_not_spawn_reviewers(coordinator, tmp_path, workload, paths):
    _, built, parent = coordinator
    created = create(parent, tmp_path, [task(workload, paths, id="small")])
    assert not stages(created, "small")
    project(parent, "run")
    (tmp_path / "app.py").write_text("mechanical change", encoding="utf-8")
    assert accept(parent, "small", artifacts=paths)["complete"]
    assert len(built) == 1


def test_explicit_two_stage_policy_supports_a_small_sdd_trial(coordinator, tmp_path):
    _, _, parent = coordinator
    created = create(parent, tmp_path, [task(id="small", review_policy="two_stage")])
    assert set(stages(created, "small")) == {"requirements", "quality"}


def test_inconclusive_requirements_never_unlock_quality_or_authorize_repair(coordinator, tmp_path, findings):
    _, built, parent = coordinator
    created = create(parent, tmp_path, [task("standard", ["app.py"], id="build")])
    review = stages(created)
    findings["requirements"] = "inconclusive"
    project(parent, "run")
    (tmp_path / "app.py").write_text("not yet independently confirmed", encoding="utf-8")
    accept(parent, "build", artifacts=["app.py"])
    project(parent, "run")
    rejected = project(parent, "verify", task=review["requirements"], attempt=1, passed=True, evidence="Assume pass.")
    assert "pass verdict" in rejected["error"]
    refused = project(parent, "request_fix", task=review["requirements"], attempt=1, evidence="No reproduced failure.")
    assert "reproduced failure" in refused["error"]
    status = project(parent, "run")
    assert not status["complete"] and status["ready"] == [] and len(built) == 2


def test_caller_cannot_supply_internal_review_stages(coordinator, tmp_path):
    home, built, parent = coordinator
    result = create(parent, tmp_path, [task(id="fake-stage", review_stage="quality")])
    assert "generated by the coordinator" in result["error"]
    assert not built and not (home / "coordinator" / "demo.json").exists()


def test_unknown_review_policy_is_rejected_before_dispatch(coordinator, tmp_path):
    home, built, parent = coordinator
    result = create(parent, tmp_path, [task("complex", ["app.py"], id="build", review_policy="skip")])
    assert "error" in result
    assert not built and not (home / "coordinator" / "demo.json").exists()


def test_quality_cannot_accept_a_receipt_from_an_older_requirements_attempt(coordinator, tmp_path, findings):
    _, _, parent = coordinator
    created = create(parent, tmp_path, [task("complex", ["app.py"], id="build")])
    review = stages(created)
    project(parent, "run")
    (tmp_path / "app.py").write_text("unchanged artifact", encoding="utf-8")
    accept(parent, "build", artifacts=["app.py"])
    project(parent, "run")
    accept(parent, review["requirements"])
    project(parent, "run")
    # A restored checkpoint may contain an older quality receipt. It must be
    # bound to the accepted requirements attempt as well as the file hashes.
    home = coordinator[0]
    file = home / "coordinator" / "demo.json"
    record = json.loads(file.read_text(encoding="utf-8"))
    record["tasks"][review["requirements"]]["attempt"] += 1
    file.write_text(json.dumps(record), encoding="utf-8")
    rejected = project(parent, "verify", task=review["quality"], attempt=1, passed=True, evidence="Stale receipt.")
    assert "prerequisite review changed" in rejected["error"]
    assert not project(parent, "status")["complete"]


def test_review_attempt_limit_survives_repeated_repairs(coordinator, tmp_path, findings):
    _, built, parent = coordinator
    created = create(parent, tmp_path, [task("complex", ["app.py"], id="build")])
    review = stages(created)
    findings["requirements"] = "needs_fix"
    for attempt in range(1, 4):
        project(parent, "run")
        (tmp_path / "app.py").write_text(f"attempt {attempt}", encoding="utf-8")
        accept(parent, "build", attempt=attempt, artifacts=["app.py"])
        project(parent, "run")
        result = project(parent, "request_fix", task=review["requirements"], attempt=attempt,
                         evidence="Reproduced the remaining requirement gap.")
        assert ("error" in result) == (attempt == 3)
    assert len(built) == 6
    assert not project(parent, "status")["complete"]
    project(parent, "run")
    assert len(built) == 6


def test_legacy_checkpoint_is_read_without_adding_calls_or_rewriting_its_graph(coordinator, tmp_path):
    from plugins.delegation.meu_coordinator.projects import open_project

    home, built, parent = coordinator
    row = {"task": task("complex", ["old.py"], id="legacy"), "state": "pending", "attempt": 0}
    record = {"schema": 1, "project": "demo", "root": str(tmp_path), "tasks": {"legacy": row}}
    directory = home / "coordinator"
    directory.mkdir()
    (directory / "demo.json").write_text(json.dumps(record), encoding="utf-8")
    with open_project(home, "demo") as state:
        assert state.record == record
    assert project(parent, "status")["ready"] == ["legacy"]
    assert not built


@pytest.mark.parametrize("backend", ["meu_coordinator", "meu_coordinator_general"])
def test_both_coordinators_use_same_review_gates_and_selected_provider(coordinator, tmp_path, findings, backend):
    import hermes_yaml as yaml

    home, built, parent = coordinator
    (home / "config.yaml").write_text(yaml.safe_dump({"delegation": {"backend": backend}}), encoding="utf-8")
    if backend.endswith("general"):
        parent.provider = "openai-codex"
        parent.base_url = "https://chatgpt.com/backend-api/codex"
        parent.model = "chosen-model"
    created = create(parent, tmp_path, [task("standard", ["app.py"], id="build")])
    review = stages(created)
    project(parent, "run")
    (tmp_path / "app.py").write_text("checked", encoding="utf-8")
    accept(parent, "build", artifacts=["app.py"])
    for stage in ("requirements", "quality"):
        project(parent, "run")
        final = accept(parent, review[stage])
    assert final["complete"] and len(built) == 3
    assert all(child["override_provider"] is None and child["routing_cfg"]["fallback_providers"] == [] for child in built)
    if backend.endswith("general"):
        assert all(child["model"] == "chosen-model" for child in built)
