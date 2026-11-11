"""After a restart a coding task is recognisable and continues only through explicit actions."""

import json

import pytest

from meu_coding.task_recovery import EXPIRED, INTERRUPTED, recovered_stage
from meu_coding.task_service import TaskError
from tests.meu_coding.phase3_support import git
from tests.meu_coding.phase5_support import approve, committed, configure_identity, service_for, start


def _restart(tmp_path):
    return service_for(tmp_path)  # same audit directory: a restarted backend


@pytest.mark.parametrize("stored, expected", [
    ("awaiting_approval", "awaiting_approval"), ("executing", "interrupted"), ("testing", "interrupted"),
    ("reviewing_diff", "interrupted"), ("integrating", "interrupted"), ("planning", "failed"),
    ("awaiting_keep_reject", "awaiting_keep_reject"), ("ready_to_commit", "ready_to_commit"),
    ("committed", "committed"), ("integration_preview", "committed"), ("integrated", "integrated"),
])
def test_every_stored_stage_has_an_explicit_recovered_stage(stored, expected):
    assert recovered_stage(stored)[0] == expected


def test_pending_approval_expires_and_can_only_be_discarded(git_repo, tmp_path):
    view = start(service_for(tmp_path), git_repo)
    restored = _restart(tmp_path)
    again = restored.get(view["task_id"])
    assert again["stage"] == "awaiting_approval" and again["error"] == EXPIRED
    assert not again["actions"]["approve"] and again["actions"]["reject"]
    with pytest.raises(TaskError, match="expired"):
        restored.decide(view["task_id"], approval_id=view["approval"]["approval_id"],
                        fingerprint=view["approval"]["fingerprint"], approve=True, approver="x")
    assert restored.reject(view["task_id"])["stage"] == "rejected"


def test_interrupted_execution_never_resumes(git_repo, tmp_path):
    service = service_for(tmp_path)
    view = approve(service, start(service, git_repo))
    audit_path = tmp_path / "audit" / f"{view['task_id']}.json"
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    data["stages"].append({"stage": "executing", "at": 0})  # the process died mid-execution
    audit_path.write_text(json.dumps(data), encoding="utf-8")
    again = _restart(tmp_path).get(view["task_id"])
    assert again["stage"] == "interrupted" and again["error"] == INTERRUPTED
    enabled = {name for name, allowed in again["actions"].items() if allowed}
    assert enabled == {"reject"}


def test_kept_result_can_be_committed_after_restart(git_repo, tmp_path):
    configure_identity(git_repo)
    service = service_for(tmp_path)
    view = approve(service, start(service, git_repo))
    service.keep(view["task_id"])
    restored = _restart(tmp_path)
    again = restored.get(view["task_id"])
    assert again["stage"] == "ready_to_commit" and again["actions"]["commit_prepare"]
    plan = restored.commit_prepare(view["task_id"])["commit"]  # verified against the reviewed digest
    done = restored.commit_confirm(view["task_id"], message="feat: after restart", token=plan["token"],
                                   confirmed=True)
    assert done["stage"] == "committed" and done["result"]["result_commit"]


def test_ready_to_integrate_survives_restart(git_repo, tmp_path):
    view = committed(service_for(tmp_path), git_repo)
    restored = _restart(tmp_path)
    again = restored.get(view["task_id"])
    assert again["stage"] == "committed" and again["result"]["result_commit"] == view["result"]["result_commit"]
    preview = restored.integration_preview(view["task_id"])
    assert preview["integration"]["preview"]["status"] == "clean"
    head = git(git_repo, "rev-parse", "HEAD")
    restored.integration_cancel(view["task_id"])
    assert git(git_repo, "rev-parse", "HEAD") == head


def test_audit_records_routing_sources_and_integration_without_secrets(git_repo, tmp_path):
    service = service_for(tmp_path)
    view = committed(service, git_repo)
    service.integration_preview(view["task_id"])
    data = json.loads((tmp_path / "audit" / f"{view['task_id']}.json").read_text(encoding="utf-8"))
    assert data["routing"]["architect"]["route"] == "fake:strong"
    assert [d["source"] for d in data["decisions"]][:2] == ["desktop", "desktop"]
    assert data["integration"]["status"] == "clean" and "token" not in json.dumps(data["integration"])
    assert data["result"]["result_commit"] and data["result"]["reviewed_diff_digest"]
    assert "def add" not in json.dumps(data)
