import json

import pytest

from meu_coding.architect import Architect
from meu_coding.coder import Coder
from meu_coding.coding_interfaces import (
    CodingTask,
    EditAction,
    EditStrategy,
    ReviewRequest,
    ReviewStatus,
)
from meu_coding.impact import ImpactAnalyzer
from meu_coding.orchestrator import CodingOrchestrator, OutcomeStatus, prepare_context
from meu_coding.provider_adapter import (
    CodingRoutes,
    ProviderError,
    ProviderSession,
    Route,
    provider_models,
)
from meu_coding.reviewer import Reviewer
from meu_coding.schemas import SchemaError, parse_json_object, validate_architect, validate_coder
from tests.meu_coding.phase2_support import TASK, make_intel

PRO, FLASH = Route("deepseek", "deepseek-pro-test"), Route("deepseek", "deepseek-flash-test")
ROUTES = CodingRoutes(architect=PRO, coder=PRO, reviewer=PRO, coder_simple=FLASH)

ARCHITECT_OK = {"summary": "clamp rate", "files_to_change": ["app/pricing.py"], "symbols_to_change": ["apply_discount"],
                "steps": ["clamp rate"], "checks": [{"kind": "unit_test", "targets": ["tests/test_pricing.py"]}],
                "risk": "low"}
CODER_OK = {"operations": [{"path": "app/pricing.py", "action": "update", "description": "clamp",
                            "search": "    return price * (1 - rate)\n",
                            "replace": "    rate = min(max(rate, 0), 1)\n    return price * (1 - rate)\n"}]}
REVIEW_OK = {"verdict": "pass", "findings": []}


class FakeClient:
    """Replies by role (detected from the system prompt); records every call."""

    def __init__(self, **replies):
        self.replies = {k: list(v) if isinstance(v, list) else [v] for k, v in replies.items()}
        self.calls = []

    def complete(self, route, messages, timeout):
        role = next(r for r in ("Architect", "Coder", "Reviewer") if f"Role: {r}" in messages[0]["content"]
                    or f"Role: independent {r}" in messages[0]["content"])
        self.calls.append((role, route, messages))
        queue = self.replies[role.lower()]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


def _run(make_repo, client, task=CodingTask(TASK)):
    intel = make_intel(make_repo)
    models = provider_models(ROUTES, client)
    orchestrator = CodingOrchestrator(intel, Coder(models.coding), Reviewer(models.review),
                                      Architect(ImpactAnalyzer(intel.graph), models.planning))
    return orchestrator.run(task), models


def test_valid_structured_responses_flow_to_approval(make_repo):
    client = FakeClient(architect=ARCHITECT_OK, coder=CODER_OK, reviewer=REVIEW_OK)
    result, models = _run(make_repo, client)
    assert result.status == OutcomeStatus.AWAITING_APPROVAL, (result.plan_errors, result.review)
    assert [c[0] for c in client.calls] == ["Architect", "Coder", "Reviewer"]
    assert result.proposal.operations[0].strategy == EditStrategy.SEARCH_REPLACE
    assert models.planning.session is not models.review.session  # reviewer state is independent
    assert all(r.ok for r in models.coding.session.calls)


def test_malformed_response_is_retried_once_then_fails_controlled(make_repo):
    client = FakeClient(architect=["not json at all", json.dumps(ARCHITECT_OK)], coder=CODER_OK, reviewer=REVIEW_OK)
    result, models = _run(make_repo, client)
    assert result.status == OutcomeStatus.AWAITING_APPROVAL
    assert models.planning.session.calls[0].attempts == 2
    assert "rejected" in client.calls[1][2][-1]["content"]

    always_bad = FakeClient(architect="{\"summary\": 1}", coder=CODER_OK, reviewer=REVIEW_OK)
    result, _ = _run(make_repo, always_bad)
    assert result.status == OutcomeStatus.PLANNING_FAILED
    assert any("summary" in e for e in result.plan_errors)
    assert not [c for c in always_bad.calls if c[0] == "Coder"]  # coder never called


def test_missing_and_unsafe_fields_are_rejected():
    with pytest.raises(SchemaError, match="files_to_change"):
        validate_architect({"summary": "x", "steps": ["s"]})
    for path in ("../escape.py", "/etc/passwd", "C:/Windows/system.ini", "a/$(rm -rf).py", "a;b.py", "a\\b.py"):
        with pytest.raises(SchemaError):
            validate_coder({"operations": [{"path": path, "search": "a", "replace": "b"}]},
                           EditStrategy.SEARCH_REPLACE)
    with pytest.raises(SchemaError, match="deleting"):
        validate_coder({"operations": [{"path": "a.py", "action": "delete"}]}, EditStrategy.SEARCH_REPLACE)
    created = validate_coder({"operations": [{"path": "new.py", "action": "create", "content": "x = 1\n"}]},
                             EditStrategy.V4A_PATCH).operations[0]
    assert created.action == EditAction.CREATE and created.strategy == EditStrategy.WHOLE_FILE


@pytest.mark.parametrize("payload", [
    {"operations": [], "command": "git reset --hard"},
    {"operations": [{"path": "a.py", "search": "a", "replace": "b", "run": "git push --force"}]},
    {"verdict": "pass", "findings": [], "approved": True},
    {"summary": "x", "approval": {"approver": "model"}},
])
def test_commands_and_self_approval_are_forbidden_anywhere(payload):
    with pytest.raises(SchemaError, match="forbidden"):
        parse_json_object(json.dumps(payload))


def test_fenced_json_is_accepted_and_garbage_is_not():
    assert parse_json_object("```json\n{\"a\": 1}\n```") == {"a": 1}
    for text in ("", "[1, 2]", "{broken", "x" * 500_000):
        with pytest.raises(SchemaError):
            parse_json_object(text)


def test_provider_errors_and_timeouts_are_controlled_failures(make_repo):
    timeout = ProviderError("deepseek:deepseek-pro-test failed: TimeoutError")
    result, _ = _run(make_repo, FakeClient(architect=timeout, coder=CODER_OK, reviewer=REVIEW_OK))
    assert result.status == OutcomeStatus.PLANNING_FAILED and "TimeoutError" in result.plan_errors[0]

    result, _ = _run(make_repo, FakeClient(architect=ARCHITECT_OK, coder=timeout, reviewer=REVIEW_OK))
    assert result.status == OutcomeStatus.NEEDS_FIX and result.approval is None  # no edits, nothing to approve

    result, _ = _run(make_repo, FakeClient(architect=ARCHITECT_OK, coder=CODER_OK, reviewer=timeout))
    assert result.status == OutcomeStatus.BLOCKED  # no independent review → no approval


def test_review_model_can_block_but_never_approve(make_repo):
    intel = make_intel(make_repo)
    task = CodingTask(TASK)
    context = prepare_context(intel, task, 8_000)
    plan = Architect(ImpactAnalyzer(intel.graph)).plan(context)
    models = provider_models(ROUTES, FakeClient(
        coder={"operations": [{"path": "web/routes.py", "search": "0.1", "replace": "0.2"}]},
        reviewer={"verdict": "pass", "findings": []}))
    proposal = Coder(models.coding).propose(task, plan, context)
    review = Reviewer(models.review).review(ReviewRequest(task, plan, proposal, context))
    assert review.status == ReviewStatus.FIX  # rules still apply; the model's "pass" grants nothing

    blocking = provider_models(ROUTES, FakeClient(reviewer={"verdict": "block", "findings": []}))
    review = Reviewer(blocking.review).review(ReviewRequest(task, plan, proposal, context))
    assert review.status == ReviewStatus.BLOCK


def test_coder_route_uses_flash_only_for_simple_low_risk_changes(make_repo):
    client = FakeClient(architect=ARCHITECT_OK, coder=CODER_OK, reviewer=REVIEW_OK)
    result, models = _run(make_repo, client)
    expected = FLASH if result.plan.risk.value == "low" else PRO
    assert models.coding.last_route == expected
    assert [c[1] for c in client.calls if c[0] == "Architect"] == [PRO]


def test_session_records_metadata_without_content():
    session = ProviderSession(FakeClient(architect=ARCHITECT_OK), ROUTES)
    session.ask("architect", PRO, "Role: Architect", {"x": 1}, validate_architect)
    record = session.calls[0]
    assert (record.role, record.route, record.ok, record.attempts) == ("architect", "deepseek:deepseek-pro-test",
                                                                      True, 1)


def test_refined_plan_can_promote_context_test_to_an_edit_target(make_repo):
    from meu_coding.architect import draft_plan
    intel = make_intel(make_repo)
    context = prepare_context(intel, CodingTask(TASK), 16_000)
    impact = ImpactAnalyzer(intel.graph)
    draft = draft_plan(context, impact)
    assert "tests/test_pricing.py" in draft.files_untouched
    client = FakeClient(architect={**ARCHITECT_OK, "files_to_change": ["app/pricing.py", "tests/test_pricing.py"]})
    model = provider_models(ROUTES, client=client).planning
    plan = Architect(impact, model).plan(context)
    assert "tests/test_pricing.py" in plan.files_to_change
    assert set(plan.files_untouched) == set(draft.files_untouched) - {"tests/test_pricing.py"}


def test_refined_plan_never_promotes_a_protected_test(make_repo):
    from meu_coding.architect import PlanningError
    from meu_coding.coding_interfaces import TaskConstraints
    intel = make_intel(make_repo)
    task = CodingTask(TASK, constraints=TaskConstraints(protected_paths=("tests/test_pricing.py",)))
    context = prepare_context(intel, task, 16_000)
    client = FakeClient(architect={**ARCHITECT_OK, "files_to_change": ["app/pricing.py", "tests/test_pricing.py"]})
    model = provider_models(ROUTES, client=client).planning
    with pytest.raises(PlanningError) as failure:
        Architect(ImpactAnalyzer(intel.graph), model).plan(context)
    assert any("protected" in error for error in failure.value.errors)
