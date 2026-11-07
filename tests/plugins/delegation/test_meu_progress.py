"""Display receipts preserve native verification and exact review ownership."""
import copy
import hashlib
import json

from plugins.delegation.meu_coordinator.progress import project_progress
from plugins.delegation.meu_coordinator.projects import Project, new_project
from plugins.delegation.meu_coordinator.workspace import workspace_plans


def task(key, **extra):
    return {"id": key, "goal": f"Produce {key}", "workload": "complex", "acceptance": "Run the import check; exactly one task must remain.",
            "parallel_safe": False, "write_paths": [], **extra}


def test_completed_helper_is_not_verified_and_progress_never_exposes_dispatch_context(tmp_path):
    record = new_project("demo", str(tmp_path), [task("build", context="private dispatch context")])
    record["tasks"]["build"].update(state="needs_review", attempt=1, result={
        "status": "completed", "summary": "raw child output", "route": {
            "provider": "openai-codex", "model": "fixture-model", "api_key": "private routing credential"}})
    before = copy.deepcopy(record)
    summary = Project(tmp_path / "demo.json", record).summary()
    row = summary["progress"][0]
    assert row["state"] == "needs_review" and row["attempt"] == 1
    assert row["acceptance"] == record["tasks"]["build"]["task"]["acceptance"]
    assert row["model"] == "fixture-model" and row["artifacts"] == []
    assert not summary["complete"] and record == before
    for private in ("private dispatch context", "raw child output", "private routing credential"):
        assert private not in json.dumps(summary["progress"])


def test_review_report_and_parent_verification_remain_distinct_and_version_bound(tmp_path):
    (tmp_path / "answer.txt").write_text("one task", encoding="utf-8")
    record = new_project("demo", str(tmp_path), [task("build", write_paths=["answer.txt"]),
        task("review", depends_on=["build"], review_of="build")])
    built = record["tasks"]["build"]
    built.update(state="verified", attempt=1, artifacts={"answer.txt": hashlib.sha256(b"one task").hexdigest()}, evidence="Import check passed.")
    reviewer = record["tasks"]["review"]
    reviewer.update(state="needs_review", attempt=1, reviewed_attempt=1, reviewed_artifacts=copy.deepcopy(built["artifacts"]),
        result={"schema_valid": True, "summary": json.dumps({"verdict": "pass", "check": "Import a duplicate ID.", "observed": "Exactly one task remained."})})
    rows = project_progress(record)
    assert rows[1]["state"] == "needs_review" and rows[1]["review"]["verdict"] == "pass"
    assert rows[0]["evidence"] == "Import check passed."
    assert rows[0]["artifacts"] == [{"name": "answer.txt", "path": str(tmp_path / "answer.txt")}]
    reviewer["state"] = "verified"
    assert project_progress(record)[1]["review"]["reviewed_attempt"] == 1
    built["attempt"] = 2
    assert project_progress(record)[1]["review"] is None


def test_retry_and_interrupted_snapshots_do_not_reuse_an_old_helpers_model(tmp_path):
    record = new_project("demo", str(tmp_path), [task("build")])
    row = record["tasks"]["build"]
    row.update(state="running", attempt=2, result={"status": "completed", "model": "previous-attempt"})
    assert project_progress(record)[0]["state"] == "running"
    idle = project_progress(record, idle=True)[0]
    assert idle["state"] == "interrupted" and idle["model"] is None
    assert record["tasks"]["build"]["state"] == "running"
    row["state"] = "pending"
    assert project_progress(record)[0]["model"] is None


def test_workspace_progress_remains_profile_owned_and_does_not_change_checkpoints(tmp_path):
    roots = []
    for profile in ("first", "second"):
        home = tmp_path / profile
        root = home / "project"
        root.mkdir(parents=True)
        directory = home / "coordinator"
        directory.mkdir()
        record = new_project("same-id", str(root), [task(profile)])
        file = directory / "same-id.json"
        file.write_text(json.dumps(record), encoding="utf-8")
        roots.append((home, root, file, file.read_bytes()))
    for home, root, file, original in roots:
        plans = workspace_plans(home, [str(root)])
        assert plans[0]["tasks"][0]["id"] == home.name
        assert plans[0]["tasks"][0]["acceptance"].startswith("Run the import")
        assert file.read_bytes() == original
        assert workspace_plans(home, [str(tmp_path / "unrelated")]) == []
