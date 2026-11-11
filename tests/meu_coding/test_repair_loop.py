import pytest

from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    EditStrategy,
    FindingCategory,
    ReviewFinding,
    ReviewResult,
    ReviewStatus,
    StrategyChoice,
)
from meu_coding.repair_loop import RepairLoop
from tests.meu_coding.phase2_support import edit

CHOICE = StrategyChoice(EditStrategy.SEARCH_REPLACE, "test", "test")


def _proposal(n: int) -> CodeChangeProposal:
    return CodeChangeProposal((edit("a.py", search=f"v{n}", replace=f"v{n + 1}"),), CHOICE)


def _result(status: ReviewStatus, repair: str = "fix it") -> ReviewResult:
    finding = ReviewFinding(FindingCategory.CORRECTNESS, status, "x")
    return ReviewResult(status, (finding,), (repair,) if status == ReviewStatus.FIX and repair else (), 0.9, "r")


class Script:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.repairs = []
        self.calls = 0

    def propose(self, repair):
        self.repairs.append(repair)
        self.calls += 1
        return _proposal(self.calls)

    def review(self, proposal):
        return _result(self.statuses[min(self.calls, len(self.statuses)) - 1])


def test_second_attempt_succeeds_with_the_reviewers_instructions():
    script = Script([ReviewStatus.FIX, ReviewStatus.PASS])
    outcome = RepairLoop().run(script.propose, script.review)
    assert outcome.status == ReviewStatus.PASS
    assert [a.number for a in outcome.attempts] == [0, 1]
    assert script.repairs[0] is None
    assert script.repairs[1].attempt == 1
    assert script.repairs[1].review.repair_instructions == ("fix it",)
    assert script.repairs[1].previous is outcome.attempts[0].proposal


def test_stops_after_max_repairs_and_records_history():
    script = Script([ReviewStatus.FIX])
    outcome = RepairLoop(max_repairs=3).run(script.propose, script.review)
    assert outcome.status == ReviewStatus.FIX
    assert len(outcome.attempts) == 4 and script.calls == 4  # initial + 3 repairs, never more
    assert "repair limit" in outcome.stop_reason


def test_block_stops_immediately():
    script = Script([ReviewStatus.BLOCK])
    outcome = RepairLoop().run(script.propose, script.review)
    assert len(outcome.attempts) == 1 and outcome.status == ReviewStatus.BLOCK


def test_no_progress_and_non_actionable_fixes_stop_early():
    same = CodeChangeProposal((edit("a.py"),), CHOICE)
    outcome = RepairLoop().run(lambda repair: same, lambda p: _result(ReviewStatus.FIX))
    assert len(outcome.attempts) == 2 and "no progress" in outcome.stop_reason

    outcome = RepairLoop().run(lambda repair: same, lambda p: _result(ReviewStatus.FIX, repair=""))
    assert len(outcome.attempts) == 1 and "actionable" in outcome.stop_reason


def test_zero_repairs_and_negative_limits():
    script = Script([ReviewStatus.FIX])
    assert len(RepairLoop(max_repairs=0).run(script.propose, script.review).attempts) == 1
    with pytest.raises(ValueError):
        RepairLoop(max_repairs=-1)
