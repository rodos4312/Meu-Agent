"""End to end: Repository Intelligence → Architect → Coder → Review → approval → isolated
worktree → MEU patch engine → real checks (py_compile, ruff when present, pytest) → actual-diff
review, stopping before any commit."""

import pytest

from meu_coding.coding_interfaces import ReviewStatus
from meu_coding.coding_session import SessionState
from meu_coding.execution import ApprovalError
from meu_coding.safe_execution import SafeExecutionAdapter
from tests.meu_coding.phase3_support import (
    TASK,
    buggy,
    fake_adapter,
    fake_runner,
    git,
    good,
    session_for,
    snapshot,
    yes,
)


def test_harmless_task_runs_end_to_end_and_stops_before_commit(git_repo, monkeypatch):
    before, head = snapshot(git_repo), git(git_repo, "rev-parse", "HEAD")
    session = session_for(git_repo, [good], adapter=SafeExecutionAdapter())  # real checks
    scans = []
    original = session.intelligence.indexer.scan
    monkeypatch.setattr(session.intelligence.indexer, "scan", lambda *a, **k: scans.append(1) or original(*a, **k))

    assert session.start(TASK) == SessionState.AWAITING_APPROVAL
    request = session.pending
    assert "+def add(a, b):" in request.preview_diff  # the user approves the exact result
    attempt = session.execute(yes(request))
    result = attempt.result

    assert result.executed, result.reasons
    assert attempt.review.status == ReviewStatus.PASS, attempt.review.rationale
    assert session.state == SessionState.REVIEWED
    assert session.stages[-4:] == ["approved", "executed", "tested", "reviewed_pass"]
    passed = {e.argv[2] if len(e.argv) > 2 else e.argv[0]: e.result.status.value for e in result.checks}
    assert passed.get("pytest") == "passed" and passed.get("py_compile") == "passed"
    assert result.fingerprint == request.fingerprint
    assert set(result.files_changed) == {"calc/ops.py", "tests/test_ops.py"}
    assert snapshot(git_repo) == before and git(git_repo, "rev-parse", "HEAD") == head
    assert result.commits == 0 and not git(git_repo, "remote").strip()  # nothing committed, nowhere to push
    assert scans == []  # no stage re-scanned the repository
    assert attempt.timings["targeted_refresh"] < 1.0 and {"apply", "checks"} <= set(attempt.timings)


def test_repair_after_failing_tests_needs_a_new_approval(git_repo):
    session = session_for(git_repo, [buggy, good], adapter=SafeExecutionAdapter())
    session.start(TASK)
    first_request = session.pending
    first = session.execute(yes(first_request))
    assert first.review.status == ReviewStatus.FIX, first.review.rationale
    assert session.can_repair

    assert session.repair() == SessionState.AWAITING_APPROVAL
    second_request = session.pending
    assert second_request.approval_id != first_request.approval_id
    assert second_request.fingerprint != first_request.fingerprint
    with pytest.raises(ApprovalError):  # the old approval cannot drive the repair
        session.execute(yes(first_request))
    assert session.state == SessionState.AWAITING_APPROVAL  # nothing ran without a new approval

    second = session.execute(yes(second_request))
    assert second.review.status == ReviewStatus.PASS, second.review.rationale
    assert [a.approval_id for a in session.attempts] == [first_request.approval_id, second_request.approval_id]
    assert session.attempts[0].result.worktree_path != session.attempts[1].result.worktree_path


def test_repairs_are_bounded(git_repo):
    session = session_for(git_repo, [buggy], adapter=fake_adapter(fake_runner(returncode=1)), max_repairs=1)
    session.start(TASK)
    assert session.execute(yes(session.pending)).review.status == ReviewStatus.FIX
    assert session.repair() == SessionState.AWAITING_APPROVAL  # repair 1 of 1
    assert session.execute(yes(session.pending)).review.status == ReviewStatus.FIX
    assert not session.can_repair and len(session.attempts) == 2
    with pytest.raises(ApprovalError):
        session.repair()
