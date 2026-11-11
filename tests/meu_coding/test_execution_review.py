"""Actual-diff review: what execution really did decides the verdict."""

from dataclasses import replace

from meu_coding.coding_interfaces import CheckKind, CheckResult, CheckSpec, CheckStatus, ReviewStatus
from meu_coding.execution_review import OverlayRefresh, impact_of, review_execution
from meu_coding.reviewer import Reviewer
from meu_coding.test_executor import ExecutedCheck
from tests.meu_coding.phase3_support import TASK, session_for, good, yes

UNIT = CheckSpec(CheckKind.UNIT_TEST, "unit tests", ("tests/test_ops.py",))
PYTEST = ("python", "-m", "pytest", "tests/test_ops.py")


def _executed(git_repo):
    session = session_for(git_repo, [good])
    session.start(TASK)
    request = session.pending
    attempt = session.execute(yes(request))
    assert attempt.result.executed, attempt.result.reasons
    return session, request, attempt.result


def _review(session, request, result, overlay=OverlayRefresh({}, 0.0)):
    return review_execution(request, result, session.context, Reviewer(), overlay,
                            impact_of(session.intelligence, result, request))


def _passing(result):
    check = ExecutedCheck(UNIT, PYTEST, CheckResult(UNIT.key, CheckStatus.PASSED, "2 passed"), 0.1)
    return replace(result, checks=(check,), check_results=(check.result,))


def test_matching_diff_and_passing_tests_pass(git_repo):
    session, request, result = _executed(git_repo)
    assert _review(session, request, _passing(result)).status == ReviewStatus.PASS


def test_unexpected_file_in_the_actual_diff_blocks(git_repo):
    session, request, result = _executed(git_repo)
    widened = _passing(replace(result, files_changed=(*result.files_changed, "calc/__init__.py")))
    review = _review(session, request, widened)
    assert review.status == ReviewStatus.BLOCK and "calc/__init__.py" in review.files_unexpectedly_touched


def test_actual_diff_missing_an_approved_file_needs_a_fix(git_repo):
    session, request, result = _executed(git_repo)
    review = _review(session, request, _passing(replace(result, files_changed=("calc/ops.py",))))
    assert review.status == ReviewStatus.FIX


def test_test_failure_needs_a_fix_and_no_tests_is_a_gap(git_repo):
    session, request, result = _executed(git_repo)
    failed = ExecutedCheck(UNIT, PYTEST, CheckResult(UNIT.key, CheckStatus.FAILED, "assert 1 == 5"), 0.1)
    review = _review(session, request, replace(result, checks=(failed,), check_results=(failed.result,)))
    assert review.status == ReviewStatus.FIX and any("assert 1 == 5" in f.message for f in review.findings)
    gap = _review(session, request, replace(result, checks=(), check_results=()))
    assert gap.status == ReviewStatus.FIX and any("no test ran" in f.message for f in gap.findings)


def test_blocked_execution_or_any_commit_blocks(git_repo):
    session, request, result = _executed(git_repo)
    assert _review(session, request, replace(result, status="blocked", reasons=("x",))).status == ReviewStatus.BLOCK
    assert _review(session, request, _passing(replace(result, commits=1))).status == ReviewStatus.BLOCK


def test_changed_file_that_no_longer_parses_needs_a_fix(git_repo):
    session, request, result = _executed(git_repo)
    broken = session.intelligence.extractor.extract("calc/ops.py", "def add(:\n", "python")
    review = _review(session, request, _passing(result), OverlayRefresh({"calc/ops.py": broken}, 0.0))
    assert review.status == ReviewStatus.FIX
