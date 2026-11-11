from dataclasses import replace

import pytest

from meu_coding.architect import Architect, PlanningError, validate_plan
from meu_coding.coding_interfaces import CheckKind, CodingTask, RiskLevel, TaskConstraints
from meu_coding.impact import ImpactAnalyzer
from meu_coding.orchestrator import prepare_context
from tests.meu_coding.phase2_support import TASK, make_intel


def _context(make_repo, task=CodingTask(TASK)):
    intel = make_intel(make_repo)
    return intel, prepare_context(intel, task, 8_000)


def test_plan_is_structured_and_targets_the_relevant_file(make_repo):
    intel, context = _context(make_repo)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    assert plan.files_to_change == ("app/pricing.py",)
    assert "apply_discount" in plan.symbols_to_change
    assert plan.steps and plan.summary.startswith("Clamp the rate")
    assert plan.test_plan.of_kind(CheckKind.UNIT_TEST)[0].targets == ("tests/test_pricing.py",)
    assert plan.test_plan.of_kind(CheckKind.SYNTAX)
    assert plan.risk in RiskLevel and plan.impact is not None
    assert plan.safety_notes and not plan.unresolved_questions


def test_protected_files_are_never_planned_and_stay_untouched(make_repo):
    task = CodingTask(TASK, TaskConstraints(protected_paths=("app/pricing.py",)), explicit_files=("app/pricing.py",))
    intel, context = _context(make_repo, task)
    with pytest.raises(PlanningError):  # the only target is protected: nothing left to plan
        Architect(ImpactAnalyzer(intel.graph)).plan(context)

    task = CodingTask(TASK, TaskConstraints(protected_paths=("web/",)))
    intel, context = _context(make_repo, task)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    assert "web/" in plan.files_untouched
    assert not any(p.startswith("web/") for p in plan.files_to_change)


def test_validation_rejects_unsafe_or_incomplete_plans(make_repo):
    intel, context = _context(make_repo)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    assert validate_plan(plan, context).ok
    for bad in (
        replace(plan, files_to_change=("../outside.py",)),
        replace(plan, files_to_change=(".env",)),
        replace(plan, files_to_change=()),
        replace(plan, steps=()),
        replace(plan, files_to_change=("missing.py",)),
        replace(plan, unresolved_questions=("which file?",)),
        replace(plan, test_plan=replace(plan.test_plan, checks=())),
    ):
        assert not validate_plan(bad, context).ok, bad


def test_no_matching_file_fails_with_a_question(make_repo):
    intel, context = _context(make_repo, CodingTask("zzqx qqvv"))
    with pytest.raises(PlanningError) as caught:
        Architect(ImpactAnalyzer(intel.graph)).plan(context)
    assert any("unresolved questions" in e or "changes no file" in e for e in caught.value.errors)


def test_planning_model_refines_but_is_still_validated(make_repo):
    intel, context = _context(make_repo)

    class Widening:
        def plan(self, request):
            assert request.draft.files_to_change == ("app/pricing.py",)
            return replace(request.draft, files_to_change=(*request.draft.files_to_change, ".git/config"),
                           impact=None)

    with pytest.raises(PlanningError) as caught:
        Architect(ImpactAnalyzer(intel.graph), Widening()).plan(context)
    assert any(".git/config" in e for e in caught.value.errors)
