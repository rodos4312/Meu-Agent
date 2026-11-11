"""Phase 4 task lifecycle: approval view, single-use decisions, proposed/actual diffs,
keep/reject, controlled commit, restore after restart. Real git + MEU worktree/patch/diff
helpers; checks run through a fake runner; work runs synchronously."""

import json

import pytest

from meu_coding import safe_execution
from meu_coding.coding_interfaces import EditStrategy
from meu_coding.provider_adapter import ProviderError, Route, resolve_coding_routes
from meu_coding.task_service import TRANSITIONS, CodingTaskService, ModelBundle, Stage, TaskError
from meu_coding.workspace import WorktreeFileOps
from tests.meu_coding.phase3_support import (
    TASK,
    ScriptedModel,
    buggy,
    fake_adapter,
    fake_runner,
    git,
    good,
    snapshot,
)


def _service(tmp_path, builders=(good,), runner=None):
    runner = runner or fake_runner()
    bundle = lambda: ModelBundle(None, ScriptedModel(list(builders)), None,
                                 {"architect": "fake:strong", "coder": "fake:strong", "reviewer": "fake:strong"},
                                 "models_by_workload")
    return CodingTaskService(models_factory=bundle, adapter_factory=lambda: fake_adapter(runner),
                             spawn=lambda fn, name: fn(), audit_directory=tmp_path / "audit")


def _start(service, repo):
    return service.start(TASK.description, str(repo), TASK.explicit_files)


def _approve(service, view, **overrides):
    approval = view["approval"]
    args = {"approval_id": approval["approval_id"], "fingerprint": approval["fingerprint"], "approve": True,
            "approver": "tester", "device": "desktop-1", **overrides}
    return service.decide(view["task_id"], **args)


def test_approval_view_shows_the_exact_fingerprinted_proposal(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _start(service, git_repo)
    assert view["stage"] == "awaiting_approval", view["error"]
    assert view["history"][:5] == ["analyzing", "planning", "coding", "reviewing", "awaiting_approval"]
    approval = view["approval"]
    pending = service.tasks[view["task_id"]].session.pending
    assert approval["fingerprint"] == pending.fingerprint and approval["approval_id"] == pending.approval_id
    assert "+def add(a, b):" in approval["proposed_diff"]
    assert approval["target_files"] == ["calc/ops.py", "tests/test_ops.py"]
    assert approval["strategy"] == EditStrategy.SEARCH_REPLACE.value
    assert approval["worktree_target"]["branch"] == "main"
    assert view["plan"]["risk"] and view["plan"]["checks"] and view["plan"]["files_to_change"]
    enabled = {name for name, allowed in view["actions"].items() if allowed}
    assert enabled == {"approve", "reject_proposal"}  # nothing else is possible before a decision


def test_wrong_or_stale_decisions_are_refused_and_a_decision_is_consumed_once(git_repo, tmp_path):
    runner = fake_runner()
    service = _service(tmp_path, runner=runner)
    view = _start(service, git_repo)
    with pytest.raises(TaskError, match="approval required again"):
        _approve(service, view, fingerprint="0" * 64)
    with pytest.raises(TaskError, match="approval required again"):  # another proposal's id, same title
        _approve(service, view, approval_id="f" * 32)
    done = _approve(service, view)
    assert done["stage"] == "awaiting_keep_reject", done["error"]
    calls = len(runner.calls)
    with pytest.raises(TaskError, match="already used"):
        _approve(service, view)  # replay, e.g. from a second device
    assert len(runner.calls) == calls  # nothing executed twice
    assert [d["decision"] for d in service.tasks[view["task_id"]].audit.decisions] == ["approve"]


def test_proposed_and_actual_diffs_are_both_shown(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    execution = view["execution"]
    assert "+def add(a, b):" in execution["actual_diff"]
    assert execution["files_changed"] == ["calc/ops.py", "tests/test_ops.py"]
    assert execution["reviewer"]["verdict"] == "pass" and execution["tests"]
    assert {"executing", "testing", "reviewing_diff"} <= set(view["history"])
    assert view["approval"] is None  # the approval card is gone once consumed


def test_actual_diff_mismatch_blocks_and_requires_a_new_approval(git_repo, tmp_path, monkeypatch):
    real_apply = safe_execution.apply_operations

    def apply_and_sneak(ops, file_ops):
        ok, error = real_apply(ops, file_ops)
        if isinstance(file_ops, WorktreeFileOps):
            file_ops.write_file("calc/extra.py", "x = 1\n")
        return ok, error

    monkeypatch.setattr(safe_execution, "apply_operations", apply_and_sneak)
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    assert view["stage"] == "blocked"
    assert view["error"].startswith("Actual diff does not match approved proposal.")
    assert not view["actions"]["keep"] and not view["actions"]["commit_prepare"]


def test_parent_change_after_approval_is_stale(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _start(service, git_repo)
    (git_repo / "calc" / "ops.py").write_text("def sub(a, b):\n    return b - a\n")
    blocked = _approve(service, view)
    assert blocked["stage"] == "blocked" and "changed after approval" in blocked["error"]


def test_reject_before_execution_revokes_the_approval(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _start(service, git_repo)
    rejected = _approve(service, view, approve=False)
    assert rejected["stage"] == "rejected" and rejected["execution"] is None
    record = service.tasks[view["task_id"]]
    assert record.session.adapter._issued[view["approval"]["approval_id"]] == "revoked"
    assert not (git_repo / ".worktrees").exists()


def test_keep_then_commit_only_with_explicit_confirmation(git_repo, tmp_path):
    git(git_repo, "config", "user.name", "Test User")
    git(git_repo, "config", "user.email", "test@example.invalid")
    before, head = snapshot(git_repo), git(git_repo, "rev-parse", "HEAD")
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    task_id = view["task_id"]
    with pytest.raises(TaskError, match="Reviewer PASS and Keep"):
        service.commit_prepare(task_id)  # not before KEEP
    kept = service.keep(task_id)
    assert kept["stage"] == "ready_to_commit" and kept["actions"]["commit_prepare"]
    prepared = service.commit_prepare(task_id)["commit"]
    assert prepared["files"] == ["calc/ops.py", "tests/test_ops.py"] and prepared["suggested_message"]
    assert prepared["branch"].startswith("hermes-subagent/") and "No push" in prepared["note"]
    for kwargs in ({"confirmed": False, "token": prepared["token"]}, {"confirmed": True, "token": "stale"}):
        with pytest.raises(TaskError):
            service.commit_confirm(task_id, message="x", **kwargs)
    done = service.commit_confirm(task_id, message="feat: add add()\n\nEdited by the user.", token=prepared["token"],
                                  confirmed=True)
    assert done["stage"] == "committed" and len(done["commit"]["hash"]) == 40
    worktree = view["execution"]["worktree"]["path"]
    assert git(worktree, "log", "-1", "--format=%s").strip() == "feat: add add()"  # the edited message
    assert snapshot(git_repo) == before and git(git_repo, "rev-parse", "HEAD") == head
    assert git(git_repo, "branch", "--show-current").strip() == "main" and not git(git_repo, "remote").strip()
    assert service.tasks[task_id].audit.commit_hash == done["commit"]["hash"]


def test_commit_refused_when_the_worktree_changed_after_review(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    service.keep(view["task_id"])
    worktree = view["execution"]["worktree"]["path"]
    with open(f"{worktree}/calc/ops.py", "a", encoding="utf-8") as handle:
        handle.write("# edited after review\n")
    with pytest.raises(TaskError, match="changed after review"):
        service.commit_prepare(view["task_id"])


def test_failed_tests_keep_without_commit_and_repair_needs_new_approval(git_repo, tmp_path):
    service = _service(tmp_path, builders=(buggy, good), runner=fake_runner(returncode=1))
    first = _approve(service, _start(service, git_repo))
    assert first["stage"] == "awaiting_keep_reject" and first["execution"]["reviewer"]["verdict"] == "fix"
    assert first["actions"]["repair"] and not first["actions"]["commit_prepare"]
    repaired = service.repair(first["task_id"])
    assert repaired["stage"] == "awaiting_approval"
    assert repaired["approval"]["approval_id"] != first["execution"]["approval_id"]
    with pytest.raises(TaskError):
        _approve(service, repaired, approval_id=first["execution"]["approval_id"],
                 fingerprint=first["execution"]["fingerprint"])
    kept = service.keep(_approve(service, repaired)["task_id"])
    assert kept["stage"] == "kept"  # tests still fail → preserved, never committable
    with pytest.raises(TaskError):
        service.commit_prepare(kept["task_id"])


def test_reject_after_execution_uses_safe_cleanup_and_keeps_when_unsure(git_repo, tmp_path, monkeypatch):
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    worktree = view["execution"]["worktree"]["path"]
    adapter = service.tasks[view["task_id"]].session.adapter
    monkeypatch.setattr(adapter.workspace, "finalize", lambda wt, discard: (_ for _ in ()).throw(OSError("probe")))
    rejected = service.reject(view["task_id"])
    assert rejected["stage"] == "rejected"
    outcome = rejected["cleanup"]["worktrees"][0]
    assert outcome["pruned"] is False and outcome["inspection_failed"]
    assert (git_repo / ".worktrees").exists() and __import__("os").path.isdir(worktree)  # preserved


def test_reject_after_execution_follows_existing_rules(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    rejected = service.reject(view["task_id"])
    outcome = rejected["cleanup"]["worktrees"][0]
    assert outcome["path"] == view["execution"]["worktree"]["path"]
    assert outcome.get("pruned") is True or outcome.get("note")  # removed (archived) or kept with a reason
    assert git(git_repo, "branch", "--show-current").strip() == "main"


def test_invalid_transitions_and_restart_never_resume(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _start(service, git_repo)
    record = service.tasks[view["task_id"]]
    with pytest.raises(TaskError):
        service._set(record, Stage.COMMITTED)
    assert Stage.EXECUTING not in TRANSITIONS[Stage.REJECTED]
    restored = _service(tmp_path)  # same audit directory: a restarted backend
    again = restored.get(view["task_id"])
    assert again["restored"] and again["stage"] == "awaiting_approval" and "expired" in again["error"]
    assert again["approval"] is None and not again["actions"]["approve"]


def test_audit_record_has_identifiers_but_no_secrets_or_content(git_repo, tmp_path):
    service = _service(tmp_path)
    view = _approve(service, _start(service, git_repo))
    data = json.loads((tmp_path / "audit" / f"{view['task_id']}.json").read_text(encoding="utf-8"))
    assert data["approval_fingerprint"] == view["execution"]["fingerprint"]
    assert data["plan_hash"] and data["proposal_fingerprint"] and data["worktree"]["path"]
    assert data["reviewer_verdict"] == "pass" and data["decisions"][0]["device"] == "desktop-1"
    assert "def add" not in json.dumps(data)  # no diff or file content


def test_coding_routes_use_existing_settings_with_a_safe_fallback():
    workload = {"smart_model_routing": {"enabled": True, "provider": "deepseek", "routes": {
        "routine": {"provider": "deepseek", "model": "deepseek-flash-x"},
        "complex": {"provider": "deepseek", "model": "deepseek-pro-x"}}}}
    resolved = resolve_coding_routes(workload)
    assert resolved.source == "models_by_workload"
    assert resolved.routes.architect == resolved.routes.reviewer == resolved.routes.coder == Route("deepseek",
                                                                                                  "deepseek-pro-x")
    assert resolved.routes.coder_simple == Route("deepseek", "deepseek-flash-x")
    fallback = resolve_coding_routes({"model": {"provider": "zai", "default": "glm-x"}})
    assert fallback.source == "main_model_fallback" and fallback.routes.coder_simple == Route("zai", "glm-x")
    assert fallback.routes.architect == Route("zai", "glm-x")
    with pytest.raises(ProviderError):
        resolve_coding_routes({})


def test_missing_model_configuration_is_actionable(git_repo, tmp_path):
    def unavailable():
        raise ProviderError("No model is configured: choose a main model or Models by workload in Settings.")

    service = CodingTaskService(models_factory=unavailable, spawn=lambda fn, name: fn(),
                                audit_directory=tmp_path / "audit")
    with pytest.raises(TaskError, match="No coding model is configured"):
        _start(service, git_repo)
    with pytest.raises(TaskError, match="git repository"):
        service.start("x", str(tmp_path))
