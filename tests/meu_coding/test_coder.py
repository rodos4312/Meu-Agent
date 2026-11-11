from meu_coding.architect import Architect
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import CodingTask, EditStrategy
from meu_coding.impact import ImpactAnalyzer
from meu_coding.orchestrator import prepare_context
from tests.meu_coding.conftest import write_tree
from tests.meu_coding.phase2_support import REPO, TASK, ScriptedCoder, edit, good_output, make_intel, output


def _setup(make_repo, model_id=""):
    intel = make_intel(make_repo)
    task = CodingTask(TASK, model_id=model_id)
    context = prepare_context(intel, task, 8_000)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    return intel, task, context, plan


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_coder_produces_a_proposal_and_never_touches_the_repository(make_repo):
    intel, task, context, plan = _setup(make_repo)
    before = _snapshot(intel.root)
    model = ScriptedCoder([good_output(assumptions=("rate is a float",), expected_tests=("tests/test_pricing.py",))])
    proposal = Coder(model).propose(task, plan, context)
    assert _snapshot(intel.root) == before
    assert proposal.affected_files == ("app/pricing.py",)
    assert proposal.assumptions == ("rate is a float",)
    assert proposal.expected_tests == ("tests/test_pricing.py",)
    assert proposal.change_descriptions == ("app/pricing.py: clamp rate in apply_discount",)
    assert not proposal.format_errors


def test_coder_receives_context_plan_and_profile_budget(make_repo):
    _, task, context, plan = _setup(make_repo, "deepseek-flash")
    model = ScriptedCoder([good_output()])
    Coder(model).propose(task, plan, context)
    request = model.requests[0]
    assert request.plan is plan and request.context is context
    assert request.max_context_chars == 8_000
    assert request.strategy.strategy == EditStrategy.WHOLE_FILE  # app/pricing.py is tiny
    assert request.strategy.reason.startswith("small file")


def test_coder_uses_the_requested_strategy(make_repo, tmp_path):
    big = dict(REPO, **{"app/pricing.py": REPO["app/pricing.py"] + "\n# padding\n" * 600})
    intel = make_intel(lambda files: write_tree(tmp_path / "big", files), big)
    task = CodingTask(TASK, model_id="deepseek-pro")
    context = prepare_context(intel, task, 8_000)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    v4a = "*** Begin Patch\n*** Update File: app/pricing.py\n@@\n-x\n+y\n*** End Patch\n"
    model = ScriptedCoder([output(edit("app/pricing.py", EditStrategy.UNIFIED_DIFF, patch=(
        "--- a/app/pricing.py\n+++ b/app/pricing.py\n@@ -1 +1 @@\n-x\n+y\n")))])
    proposal = Coder(model, requested_strategy=EditStrategy.UNIFIED_DIFF).propose(task, plan, context)
    assert proposal.strategy.strategy == EditStrategy.UNIFIED_DIFF and not proposal.format_errors

    default = Coder(ScriptedCoder([output(edit("app/pricing.py", EditStrategy.V4A_PATCH, patch=v4a))]))
    assert default.propose(task, plan, context).strategy.strategy == EditStrategy.V4A_PATCH


def test_strategy_mismatch_and_malformed_payload_are_recorded(make_repo):
    _, task, context, plan = _setup(make_repo)
    model = ScriptedCoder([output(edit("app/pricing.py", EditStrategy.V4A_PATCH, patch="+oops\n"))])
    proposal = Coder(model).propose(task, plan, context)
    assert any("expected search_replace" in e for e in proposal.format_errors)
    assert any("Begin Patch" in e for e in proposal.format_errors)
