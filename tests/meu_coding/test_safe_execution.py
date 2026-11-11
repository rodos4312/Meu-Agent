"""SafeExecutionAdapter against a real temporary git repository and MEU's real worktree,
patch and diff helpers. Checks run through a fake runner here (no processes)."""

from dataclasses import replace

import pytest

from meu_coding.coding_interfaces import EditAction, EditOperation, EditStrategy, TaskConstraints
from meu_coding.execution import ApprovalError
from meu_coding.safe_execution import (
    ApprovedExecution,
    ExecutionBlocked,
    ExecutionDecision,
    approve_execution,
)
from meu_coding.workspace import WorktreeFileOps, WorkspaceError
from tests.meu_coding.phase3_support import (
    TASK,
    commit_all,
    edits,
    fake_adapter,
    fake_runner,
    git,
    good,
    session_for,
    snapshot,
    yes,
)


def _pending(git_repo, builder=good, adapter=None, task=TASK):
    session = session_for(git_repo, [builder], adapter)
    session.start(task)
    assert session.pending is not None, (session.state, session.blocked_reason, session.planning.review)
    return session, session.pending


def test_approved_proposal_executes_in_an_isolated_worktree(git_repo):
    before, head = snapshot(git_repo), git(git_repo, "rev-parse", "HEAD")
    runner = fake_runner()
    session, request = _pending(git_repo, adapter=fake_adapter(runner))
    result = session.execute(yes(request)).result
    assert result.executed, result.reasons
    assert snapshot(git_repo) == before  # parent checkout untouched
    assert git(git_repo, "rev-parse", "HEAD") == head and git(git_repo, "branch", "--show-current").strip() == "main"
    worktree = result.worktree_path
    assert "def add(a, b)" in open(f"{worktree}/calc/ops.py", encoding="utf-8").read()
    assert result.files_changed == ("calc/ops.py", "tests/test_ops.py")
    assert result.additions >= 7 and result.deletions == 0
    assert result.commits == 0 and result.commit_status == "not committed"
    assert result.worktree_state["pruned"] is False  # kept for the user to inspect
    assert result.fingerprint == request.fingerprint and result.approval_id == request.approval_id
    assert all(cwd == worktree for _argv, cwd in runner.calls)


def test_unapproved_or_mismatched_decisions_never_execute(git_repo):
    session, request = _pending(git_repo)
    for decision in (ExecutionDecision(False, "u", request.approval_id, request.fingerprint),
                     ExecutionDecision(True, "", request.approval_id, request.fingerprint),
                     ExecutionDecision(True, "u", "other", request.fingerprint),
                     ExecutionDecision(True, "u", request.approval_id, "0" * 64)):
        with pytest.raises(ApprovalError):
            session.execute(decision)
    with pytest.raises(ApprovalError):  # an approval cannot be forged
        ApprovedExecution(request, yes(request), None)
    assert not (git_repo / ".worktrees").exists()  # nothing was even opened


def test_proposal_changed_after_approval_is_blocked(git_repo):
    adapter = fake_adapter()
    _session, request = _pending(git_repo, adapter=adapter)
    sneaky = replace(request.change.proposal.operations[0], replace="def add(a, b):\n    import os\n")
    tampered = replace(request, change=replace(request.change, proposal=replace(
        request.change.proposal, operations=(sneaky, *request.change.proposal.operations[1:]))))
    with pytest.raises(ApprovalError):
        approve_execution(tampered, yes(request))
    with pytest.raises(ApprovalError):
        approve_execution(replace(request, task=replace(request.task, description="something else")), yes(request))


@pytest.mark.parametrize("op, constraints", [
    (EditOperation("AGENTS.md", EditStrategy.SEARCH_REPLACE, "x", search="# rules", replace="# none"),
     TaskConstraints(protected_paths=("AGENTS.md",))),
    (EditOperation("calc/ops.py", EditStrategy.V4A_PATCH, "x", patch=(
        "*** Begin Patch\n*** Update File: calc/ops.py\n@@\n-def sub(a, b):\n+def sub(a, b):  # x\n"
        "*** Update File: calc/__init__.py\n+import os\n*** End Patch\n")), TaskConstraints()),
    (EditOperation("calc/ops.py", EditStrategy.V4A_PATCH, "x", patch=(
        "*** Begin Patch\n*** Delete File: calc/ops.py\n*** End Patch\n")), TaskConstraints()),
    (EditOperation("../outside.py", EditStrategy.WHOLE_FILE, "x", EditAction.CREATE, content="x\n"),
     TaskConstraints()),
    (EditOperation("calc/new.py", EditStrategy.WHOLE_FILE, "x", EditAction.CREATE, content="x\n"),
     TaskConstraints()),
])
def test_scope_expansion_protected_and_escaping_edits_are_blocked(git_repo, op, constraints):
    adapter = fake_adapter()
    _session, request = _pending(git_repo, adapter=adapter)
    plan = replace(request.change.plan, files_to_change=(*request.change.plan.files_to_change, "AGENTS.md"))
    change = replace(request.change, plan=plan, proposal=replace(request.change.proposal, operations=(op,)))
    with pytest.raises(ExecutionBlocked):
        adapter.prepare(replace(request.task, constraints=constraints), change, git_repo)


def test_approval_is_single_use_and_revocable(git_repo):
    adapter = fake_adapter()
    _session, request = _pending(git_repo, adapter=adapter)
    approved = approve_execution(request, yes(request))
    assert adapter.execute(approved).executed
    again = adapter.execute(approved)
    assert again.status == "blocked" and "used" in again.reasons[0]

    second = adapter.prepare(request.task, request.change, git_repo)
    adapter.revoke(second.approval_id)
    revoked = adapter.execute(approve_execution(second, yes(second)))
    assert revoked.status == "blocked" and "revoked" in revoked.reasons[0]


def test_new_commit_after_approval_invalidates_the_workspace_identity(git_repo):
    adapter = fake_adapter()
    _session, request = _pending(git_repo, adapter=adapter)
    (git_repo / "README.md").write_text("x\n")
    commit_all(git_repo, "moved on")
    result = adapter.execute(approve_execution(request, yes(request)))
    assert result.status == "blocked" and "identity changed" in result.reasons[0]


def test_target_edited_in_the_parent_after_approval_is_stale(git_repo):
    adapter = fake_adapter()
    _session, request = _pending(git_repo, adapter=adapter)
    (git_repo / "calc" / "ops.py").write_text("def sub(a, b):\n    return b - a\n")
    result = adapter.execute(approve_execution(request, yes(request)))
    assert result.status == "blocked" and "changed since approval" in result.reasons[0]


def test_failed_apply_keeps_the_parent_safe_and_commits_nothing(git_repo, monkeypatch):
    adapter = fake_adapter()
    _session, request = _pending(git_repo, adapter=adapter)
    before, head = snapshot(git_repo), git(git_repo, "rev-parse", "HEAD")
    from meu_coding import safe_execution

    monkeypatch.setattr(safe_execution, "apply_operations", lambda ops, file_ops: (False, "simulated failure"))
    result = adapter.execute(approve_execution(request, yes(request)))
    assert result.status == "failed" and "simulated failure" in result.reasons[0]
    assert snapshot(git_repo) == before and git(git_repo, "rev-parse", "HEAD") == head
    assert git(git_repo, "branch", "--show-current").strip() == "main"
    assert result.worktree_state.get("pruned") is True  # nothing written: existing rules removed it


def test_checks_that_modify_the_worktree_block_the_result(git_repo):
    def meddling_runner(argv, cwd, env, timeout):
        from pathlib import Path

        Path(cwd, "calc", "ops.py").write_text("hacked = True\n")
        return fake_runner()(argv, cwd, env, timeout)

    session, request = _pending(git_repo, adapter=fake_adapter(meddling_runner))
    result = session.execute(yes(request)).result
    assert result.status == "blocked" and any("modified the worktree" in r for r in result.reasons)


def test_worktree_file_ops_refuse_escapes_and_destruction(tmp_path):
    ops = WorktreeFileOps(tmp_path)
    for path in ("../x.py", "/abs.py", "a/../../x.py", "C:/x.py"):
        with pytest.raises(WorkspaceError):
            ops.confine(path)
    assert ops.delete_file("a.py").error and ops.move_file("a.py", "b.py").error


def test_unexpected_extra_edit_in_coder_output_never_reaches_the_worktree(git_repo):
    def extra(request):
        return edits(request, ("calc/ops.py", ("def sub(a, b):\n", "def add(a, b):\n    return a + b\n\n\n"
                                                                    "def sub(a, b):\n")),
                     ("calc/__init__.py", ("", "import os\n")))
    session = session_for(git_repo, [extra])
    session.start(TASK)
    assert session.pending is None and session.state.value in ("needs_fix", "blocked")
