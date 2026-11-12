from dataclasses import replace

import pytest

from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    EditStrategy,
    ImplementationPlan,
    ReviewResult,
    ReviewStatus,
    RiskLevel,
    StrategyChoice,
    TestPlan,
)
from meu_coding.safe_execution import ApprovalDecision, ApprovalError, ApprovalRequest, ApprovedChange, approve
from meu_coding.workspace import unified_to_v4a
from tests.meu_coding.phase2_support import FIX_EDIT, edit

PLAN = ImplementationPlan("s", ("app/pricing.py",), (), (), ("step",), TestPlan(), RiskLevel.LOW)
PASSED = ReviewResult(ReviewStatus.PASS, (), (), 0.9, "ok")
CHOICE = StrategyChoice(EditStrategy.SEARCH_REPLACE, "p", "r")


def _request(*ops) -> ApprovalRequest:
    return ApprovalRequest.for_review(PLAN, CodeChangeProposal(ops or (FIX_EDIT,), CHOICE), PASSED)


def test_only_a_passed_review_can_request_approval():
    for status in (ReviewStatus.FIX, ReviewStatus.BLOCK):
        with pytest.raises(ApprovalError):
            ApprovalRequest.for_review(PLAN, CodeChangeProposal((FIX_EDIT,), CHOICE), replace(PASSED, status=status))


def test_approval_needs_an_explicit_matching_yes():
    request = _request()
    with pytest.raises(ApprovalError):
        approve(request, ApprovalDecision(False, "user", request.fingerprint))
    with pytest.raises(ApprovalError):
        approve(request, ApprovalDecision(True, "", request.fingerprint))
    with pytest.raises(ApprovalError):
        approve(request, ApprovalDecision(True, "user", "0" * 64))
    tampered = replace(request, proposal=replace(request.proposal, operations=(edit("app/pricing.py"),)))
    with pytest.raises(ApprovalError):
        approve(tampered, ApprovalDecision(True, "user", request.fingerprint))
    assert approve(request, ApprovalDecision(True, "user", request.fingerprint)).decision.approver == "user"


def test_approved_change_cannot_be_forged():
    request = _request()
    with pytest.raises(ApprovalError):
        ApprovedChange(request, ApprovalDecision(True, "user", request.fingerprint))


def test_unified_diff_new_and_deleted_files():
    diff = "--- /dev/null\n+++ b/n.py\n@@ -0,0 +1 @@\n+print(1)\n--- a/o.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    assert unified_to_v4a(diff) == ("*** Begin Patch\n*** Add File: n.py\n+print(1)\n"
                                    "*** Delete File: o.py\n*** End Patch\n")
