from dataclasses import replace

import pytest

from meu_coding.coding_interfaces import (
    CodeChangeProposal,
    EditAction,
    EditStrategy,
    ImplementationPlan,
    ReviewResult,
    ReviewStatus,
    RiskLevel,
    StrategyChoice,
    TestPlan,
)
from meu_coding.execution import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovedChange,
    MeuToolCallAdapter,
    approve,
    unified_to_v4a,
)
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
    with pytest.raises(ApprovalError):
        MeuToolCallAdapter().tool_calls(request)


def test_adapter_maps_every_strategy_onto_existing_meu_tools():
    v4a = "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch\n"
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@ def f\n ctx\n-x\n+y\n"
    request = _request(
        FIX_EDIT,
        edit("new.py", EditStrategy.WHOLE_FILE, EditAction.CREATE, content="x = 1\n"),
        edit("a.py", EditStrategy.V4A_PATCH, patch=v4a),
        edit("a.py", EditStrategy.UNIFIED_DIFF, patch=diff),
        edit("old.py", EditStrategy.SEARCH_REPLACE, EditAction.DELETE),
    )
    calls = MeuToolCallAdapter().tool_calls(approve(request, ApprovalDecision(True, "u", request.fingerprint)))
    assert [c.name for c in calls] == ["patch", "write_file", "patch", "patch", "patch"]
    assert calls[0].args == {"mode": "replace", "path": "app/pricing.py",
                             "old_string": FIX_EDIT.search, "new_string": FIX_EDIT.replace}
    assert calls[1].args == {"path": "new.py", "content": "x = 1\n"}
    assert calls[2].args == {"mode": "patch", "patch": v4a}
    assert calls[3].args["patch"] == "*** Begin Patch\n*** Update File: a.py\n@@\n ctx\n-x\n+y\n*** End Patch\n"
    assert "*** Delete File: old.py" in calls[4].args["patch"]


def test_unified_diff_new_and_deleted_files():
    diff = "--- /dev/null\n+++ b/n.py\n@@ -0,0 +1 @@\n+print(1)\n--- a/o.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n"
    assert unified_to_v4a(diff) == ("*** Begin Patch\n*** Add File: n.py\n+print(1)\n"
                                    "*** Delete File: o.py\n*** End Patch\n")
