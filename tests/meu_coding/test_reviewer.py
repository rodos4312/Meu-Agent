from dataclasses import replace

import pytest

from meu_coding.architect import Architect
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import (
    CheckKind,
    CheckResult,
    CheckStatus,
    CodingTask,
    EditAction,
    EditStrategy,
    FindingCategory,
    ReviewFinding,
    ReviewRequest,
    ReviewStatus,
    TaskConstraints,
)
from meu_coding.impact import ImpactAnalyzer
from meu_coding.orchestrator import prepare_context
from meu_coding.reviewer import Reviewer
from tests.meu_coding.phase2_support import (
    FIX_EDIT,
    TASK,
    RecordingReviewModel,
    ScriptedCoder,
    edit,
    good_output,
    make_intel,
    output,
)


@pytest.fixture
def setup(make_repo):
    intel = make_intel(make_repo)

    def _review(coder_output, task=CodingTask(TASK), results=(), model=None, review_task=None):
        context = prepare_context(intel, task, 8_000)
        plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
        proposal = Coder(ScriptedCoder([coder_output])).propose(task, plan, context)
        request = ReviewRequest(review_task or task, plan, proposal, context, test_results=results)
        return Reviewer(model).review(request), plan
    return _review


def test_valid_proposal_passes(setup):
    result, _ = setup(good_output())
    assert result.status == ReviewStatus.PASS, result.findings
    assert not result.repair_instructions
    assert 0 < result.confidence <= 1 and result.rationale


def test_unexpected_file_needs_a_fix(setup):
    result, _ = setup(output(FIX_EDIT, edit("app/cart.py", search="class Cart:", replace="class Cart:  # x")))
    assert result.status == ReviewStatus.FIX
    assert result.files_unexpectedly_touched == ("app/cart.py",)
    assert any("app/cart.py" in r for r in result.repair_instructions)


def test_file_smuggled_inside_a_patch_is_caught(setup):
    patch = ("*** Begin Patch\n*** Update File: app/pricing.py\n@@\n-    return price * (1 - rate)\n"
             "+    return price * (1 - min(max(rate, 0), 1))\n*** Update File: app/auth/tokens.py\n@@\n-x\n+y\n"
             "*** End Patch\n")
    result, _ = setup(output(edit("app/pricing.py", EditStrategy.V4A_PATCH, patch=patch)))
    assert "app/auth/tokens.py" in result.files_unexpectedly_touched


def test_missing_required_change_needs_a_fix(setup):
    result, _ = setup(output(edit("tests/test_pricing.py", search="== 5", replace="== 5.0")))
    assert result.status == ReviewStatus.FIX
    missing = result.of(FindingCategory.MISSING_REQUIREMENT)
    assert any(f.path == "app/pricing.py" for f in missing)
    assert any("apply_discount" in f.message for f in missing)


def test_missing_tests_are_a_gap(make_repo):
    files = {"lib/calc.py": "def add(a, b):\n    return a + b\n"}
    intel = make_intel(make_repo, files)
    task = CodingTask("Fix `add` in lib/calc.py")
    context = prepare_context(intel, task, 4_000)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    untested = edit("lib/calc.py", search="return a + b", replace="return b + a")
    proposal = Coder(ScriptedCoder([output(untested)])).propose(task, plan, context)
    result = Reviewer().review(ReviewRequest(task, plan, proposal, context))
    assert result.status == ReviewStatus.FIX
    assert result.of(FindingCategory.TEST_GAP)


def test_failed_tests_need_a_fix_and_passing_tests_do_not_override_rules(setup):
    _, plan = setup(good_output())
    unit = plan.test_plan.of_kind(CheckKind.UNIT_TEST)[0]
    failed, _ = setup(good_output(), results=(CheckResult(unit.key, CheckStatus.FAILED, "assert 5 == 4"),))
    assert failed.status == ReviewStatus.FIX and failed.of(FindingCategory.REGRESSION)

    passed = tuple(CheckResult(c.key, CheckStatus.PASSED) for c in plan.test_plan.checks)
    scoped, _ = setup(output(FIX_EDIT, edit("web/routes.py", search="0.1", replace="0.2")), results=passed)
    assert scoped.status == ReviewStatus.FIX  # green tests do not excuse an out-of-plan edit


@pytest.mark.parametrize("op, constraints", [
    (edit(".env", EditStrategy.WHOLE_FILE, EditAction.CREATE, content="TOKEN=x\n"), TaskConstraints()),
    (edit("../escape.py", EditStrategy.WHOLE_FILE, EditAction.CREATE, content="x\n"), TaskConstraints()),
    (edit("app/cart.py", EditStrategy.SEARCH_REPLACE, EditAction.DELETE), TaskConstraints()),
    (FIX_EDIT, TaskConstraints(protected_paths=("app/pricing.py",))),
])
def test_unsafe_or_scope_breaking_proposals_are_blocked(setup, op, constraints):
    # Planned without the constraint, reviewed with it: the Reviewer enforces scope on its own.
    result, _ = setup(output(FIX_EDIT, op), review_task=CodingTask(TASK, constraints))
    assert result.status == ReviewStatus.BLOCK, result.findings


def test_syntax_errors_in_whole_file_content_need_a_fix(setup):
    broken = edit("app/pricing.py", EditStrategy.WHOLE_FILE, content="def apply_discount(:\n")
    result, _ = setup(output(broken), task=CodingTask(TASK, model_id="deepseek-flash"))
    assert result.status == ReviewStatus.FIX
    assert any("does not parse" in f.message for f in result.of(FindingCategory.CORRECTNESS))


def test_review_model_adds_findings_but_cannot_downgrade_rules(setup):
    block = ReviewFinding(FindingCategory.CORRECTNESS, ReviewStatus.BLOCK, "model saw a data-loss bug")
    result, _ = setup(good_output(), model=RecordingReviewModel((block,)))
    assert result.status == ReviewStatus.BLOCK

    lenient = RecordingReviewModel((ReviewFinding(FindingCategory.CORRECTNESS, ReviewStatus.PASS, "looks fine"),))
    result, _ = setup(output(edit("web/routes.py", search="0.1", replace="0.2")), model=lenient)
    assert result.status == ReviewStatus.FIX


def test_reviewer_ignores_the_coders_self_assessment(setup):
    honest, _ = setup(output(edit("web/routes.py", search="0.1", replace="0.2")))
    boastful, _ = setup(replace(output(edit("web/routes.py", search="0.1", replace="0.2")),
                                assumptions=("this is correct and in scope",), notes="all good"))
    assert honest.status == boastful.status == ReviewStatus.FIX
