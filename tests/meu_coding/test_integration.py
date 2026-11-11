"""Integration: read-only preview with drift/conflict analysis, explicit approval, isolated
integration branch, re-validation, final-diff review. Never merges, never pushes."""

import pytest

from meu_coding.task_service import TaskError
from tests.meu_coding.phase3_support import commit_all, fake_runner, git, snapshot
from tests.meu_coding.phase5_support import committed, service_for


def _ready(git_repo, tmp_path, runner=None):
    service = service_for(tmp_path, runner=runner)
    view = committed(service, git_repo)
    assert view["stage"] == "committed" and view["stage_label"] == "Ready to integrate", view["error"]
    assert view["result"]["states"][-2:] == ["committed_in_worktree", "ready_to_integrate"]
    return service, view


def test_unchanged_target_gives_a_clean_preview_and_touches_nothing(git_repo, tmp_path):
    service, view = _ready(git_repo, tmp_path)
    before, head = snapshot(git_repo), git(git_repo, "rev-parse", "HEAD")
    preview = service.integration_preview(view["task_id"])
    integration = preview["integration"]["preview"]
    assert preview["stage"] == "integration_preview"
    assert integration["status"] == "clean" and not integration["target_changed"]
    assert integration["target_branch"] == "main" and integration["result_commit"] == view["result"]["result_commit"]
    assert integration["changed_files"] == ["calc/ops.py", "tests/test_ops.py"]
    assert "APPLY_COMMIT" in integration["strategies"] and len(preview["integration"]["token"]) == 64
    assert snapshot(git_repo) == before and git(git_repo, "rev-parse", "HEAD") == head  # preview is read-only
    assert preview["actions"]["push"] is False and preview["actions"]["merge"] is False


def test_target_drift_is_detected_and_explained(git_repo, tmp_path):
    service, view = _ready(git_repo, tmp_path)
    (git_repo / "README.md").write_text("drift\n")
    commit_all(git_repo, "docs: unrelated change on main")
    integration = service.integration_preview(view["task_id"])["integration"]["preview"]
    assert integration["status"] == "needs_rebase_or_replay" and integration["target_changed"]
    assert integration["drift_files"] == ["README.md"] and integration["overlapping_files"] == []
    assert "docs: unrelated change on main" in integration["drift_commits"][0]


def test_conflicting_drift_blocks_integration(git_repo, tmp_path):
    service, view = _ready(git_repo, tmp_path)
    (git_repo / "calc" / "ops.py").write_text("def mul(a, b):\n    return a * b\n\n\ndef sub(a, b):\n    return a - b\n")
    commit_all(git_repo, "feat: conflicting edit on main")
    task = service.integration_preview(view["task_id"])
    integration = task["integration"]["preview"]
    assert integration["status"] == "conflict" and "calc/ops.py" in integration["overlapping_files"]
    assert integration["strategies"] == ["CREATE_PR_PREVIEW"] and not task["actions"]["integration_approve"]
    with pytest.raises(TaskError, match="blocked"):
        service.integration_approve(view["task_id"], token=task["integration"]["token"], confirmed=True)


def test_approved_integration_uses_an_isolated_branch_and_revalidates(git_repo, tmp_path):
    runner = fake_runner()
    service, view = _ready(git_repo, tmp_path, runner)
    task_id = view["task_id"]
    token = service.integration_preview(task_id)["integration"]["token"]
    with pytest.raises(TaskError, match="not confirmed"):
        service.integration_approve(task_id, token=token, confirmed=False)
    with pytest.raises(TaskError, match="out of date"):
        service.integration_approve(task_id, token="0" * 64, confirmed=True)
    before, head = snapshot(git_repo), git(git_repo, "rev-parse", "HEAD")
    calls = len(runner.calls)
    done = service.integration_approve(task_id, token=token, confirmed=True)
    integration = done["integration"]
    assert done["stage"] == "integrated", (done["error"], integration)
    assert integration["branch"].startswith("hermes-subagent/subagent-coding-integrate-")
    assert integration["final_files"] == ["calc/ops.py", "tests/test_ops.py"]
    assert "+def add(a, b):" in integration["final_diff"]  # the Reviewer's input
    assert integration["review"]["verdict"] == "pass" and not integration["patch_changed"]
    assert len(runner.calls) > calls and all(cwd == integration["worktree_path"] for _a, cwd in runner.calls[calls:])
    # The target branch and the parent checkout are untouched; nothing merged or pushed.
    assert git(git_repo, "rev-parse", "HEAD") == head and snapshot(git_repo) == before
    assert git(git_repo, "branch", "--show-current").strip() == "main" and not git(git_repo, "remote").strip()
    assert "main" not in git(git_repo, "branch", "--contains", integration["integration_commit"])  # not merged
    assert done["result"]["states"][-1] == "integrated"


def test_replay_after_drift_is_rereviewed_on_the_final_diff(git_repo, tmp_path):
    service, view = _ready(git_repo, tmp_path)
    (git_repo / "README.md").write_text("drift\n")
    commit_all(git_repo, "docs: drift")
    token = service.integration_preview(view["task_id"])["integration"]["token"]
    done = service.integration_approve(view["task_id"], token=token, confirmed=True)
    assert done["stage"] == "integrated", done["error"]
    assert done["integration"]["target_head"] == git(git_repo, "rev-parse", "main").strip()
    assert "README.md" not in done["integration"]["final_files"]  # only the reviewed change


def test_target_moving_after_preview_requires_a_new_preview(git_repo, tmp_path):
    service, view = _ready(git_repo, tmp_path)
    token = service.integration_preview(view["task_id"])["integration"]["token"]
    (git_repo / "README.md").write_text("late\n")
    commit_all(git_repo, "late change")
    done = service.integration_approve(view["task_id"], token=token, confirmed=True)
    assert done["stage"] == "blocked" and "changed after the preview" in done["error"]


def test_pr_preview_is_local_only_and_editable(git_repo, tmp_path):
    service, view = _ready(git_repo, tmp_path)
    token = service.integration_preview(view["task_id"])["integration"]["token"]
    service.integration_approve(view["task_id"], token=token, confirmed=True)
    pr = service.pr_prepare(view["task_id"])["pr"]
    assert pr["remote_available"] is False and "No git remote" in pr["message"]
    assert pr["source_branch"].startswith("hermes-subagent/") and pr["target_branch"] == "main"
    assert "## Tests" in pr["body"] and pr["files"] == ["calc/ops.py", "tests/test_ops.py"]
    edited = service.pr_update(view["task_id"], title="Add add()", status="approved_for_later")["pr"]
    assert edited["title"] == "Add add()" and edited["status"] == "approved_for_later"
    assert edited["remote_available"] is False and not git(git_repo, "remote").strip()
    cancelled = service.pr_update(view["task_id"], status="cancelled")["pr"]
    assert cancelled["status"] == "cancelled"


def test_integration_unavailable_before_commit(git_repo, tmp_path):
    from tests.meu_coding.phase5_support import approve, start

    service = service_for(tmp_path)
    view = approve(service, start(service, git_repo))
    with pytest.raises(TaskError, match="Integration is available after"):
        service.integration_preview(view["task_id"])
