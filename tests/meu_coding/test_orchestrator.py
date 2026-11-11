import pytest

from meu_coding import CodingOrchestrator, CodingTask, OutcomeStatus
from meu_coding.architect import PlanningError
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import EditAction, EditStrategy, ReviewStatus
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

OUT_OF_SCOPE = edit("web/routes.py", search="0.1", replace="0.2")


def _run(make_repo, outputs, task=CodingTask(TASK), **kwargs):
    intel = make_intel(make_repo)
    model = ScriptedCoder(outputs)
    orchestrator = CodingOrchestrator(intel, Coder(model), **kwargs)
    return orchestrator.run(task), model, intel


def test_stages_run_in_order_and_end_at_the_approval_boundary(make_repo):
    result, model, _ = _run(make_repo, [good_output()])
    assert result.status == OutcomeStatus.AWAITING_APPROVAL
    assert result.stages == ("context", "architect", "coder", "reviewer", "approval_boundary")
    assert result.approval is not None and result.approval.proposal is result.proposal
    assert result.review.status == ReviewStatus.PASS
    assert result.impact.changed_files == ("app/pricing.py",)
    assert len(model.requests) == 1


def test_architect_failure_stops_before_the_coder(make_repo):
    result, model, _ = _run(make_repo, [good_output()], task=CodingTask("zzqx qqvv"))
    assert result.status == OutcomeStatus.PLANNING_FAILED
    assert result.stages == ("context", "architect")
    assert result.plan_errors and not model.requests and result.approval is None


def test_architect_exception_from_a_model_stops_the_flow(make_repo):
    intel = make_intel(make_repo)

    class Failing:
        def plan(self, context):
            raise PlanningError("model could not plan", ("timeout",))

    model = ScriptedCoder([good_output()])
    result = CodingOrchestrator(intel, Coder(model), architect=Failing()).run(CodingTask(TASK))
    assert result.status == OutcomeStatus.PLANNING_FAILED and result.plan_errors == ("timeout",)
    assert not model.requests


def test_reviewer_block_stops_the_flow(make_repo):
    delete = edit("app/cart.py", EditStrategy.SEARCH_REPLACE, EditAction.DELETE)
    result, model, _ = _run(make_repo, [output(FIX_EDIT, delete), good_output()])
    assert result.status == OutcomeStatus.BLOCKED
    assert result.stages == ("context", "architect", "coder", "reviewer")
    assert len(model.requests) == 1 and result.approval is None


def test_reviewer_fix_triggers_a_repair_that_can_pass(make_repo):
    result, model, _ = _run(make_repo, [output(FIX_EDIT, OUT_OF_SCOPE), good_output()])
    assert result.status == OutcomeStatus.AWAITING_APPROVAL
    assert result.stages == ("context", "architect", "coder", "reviewer", "repair", "reviewer",
                             "approval_boundary")
    repair = model.requests[1].repair
    assert repair is not None and repair.attempt == 1
    assert any("web/routes.py" in r for r in repair.review.repair_instructions)
    assert [a.review.status for a in result.attempts] == [ReviewStatus.FIX, ReviewStatus.PASS]


def test_max_repair_attempts_are_respected(make_repo):
    variants = [output(FIX_EDIT, edit("web/routes.py", search="0.1", replace=f"0.{n}")) for n in range(2, 9)]
    result, model, _ = _run(make_repo, variants, max_repairs=2)
    assert result.status == OutcomeStatus.NEEDS_FIX
    assert len(model.requests) == 3 and len(result.attempts) == 3
    assert result.approval is None and "repair limit" in result.repair.stop_reason


def test_one_task_scans_the_repository_at_most_once(make_repo, monkeypatch):
    intel = make_intel(make_repo)
    scans, contexts, ranks = [], [], []
    original_scan, original_context, original_rank = intel.indexer.scan, intel.context_with_ranking, intel.rank
    monkeypatch.setattr(intel.indexer, "scan", lambda *a, **k: scans.append(1) or original_scan(*a, **k))
    monkeypatch.setattr(intel, "context_with_ranking",
                        lambda *a, **k: contexts.append(1) or original_context(*a, **k))
    monkeypatch.setattr(intel, "rank", lambda *a, **k: ranks.append(1) or original_rank(*a, **k))
    model = ScriptedCoder([output(FIX_EDIT, OUT_OF_SCOPE), output(FIX_EDIT, edit("web/routes.py", search="0.1",
                                                                                 replace="0.3")), good_output()])
    result = CodingOrchestrator(intel, Coder(model)).run(CodingTask(TASK))
    assert len(result.attempts) == 3
    assert scans == []  # the already-built index is reused; no stage rescans
    assert contexts == [1]  # one context query shared by every stage and attempt
    assert len(ranks) <= 2  # Phase 1 ranks, deepens, re-ranks once; Phase 2 adds no ranking
    assert len({id(r.context) for r in model.requests}) == 1

    intel.refresh_changed_files(["app/pricing.py"])
    CodingOrchestrator(intel, Coder(ScriptedCoder([good_output()]))).run(
        CodingTask(TASK), refresh_paths=["app/pricing.py"])
    assert scans == []  # a targeted refresh re-reads the named files, never the tree


def test_reviewer_and_coder_cannot_share_a_model_instance(make_repo):
    intel = make_intel(make_repo)
    shared = RecordingReviewModel()
    shared.propose = lambda request: good_output()
    with pytest.raises(ValueError):
        CodingOrchestrator(intel, Coder(shared), Reviewer(shared))
