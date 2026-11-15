"""An out-of-plan edit must cost one Coder retry, not a model review of a discarded proposal."""
import json

from meu_coding.orchestrator import OutcomeStatus
from tests.meu_coding.test_provider_adapter import ARCHITECT_OK, CODER_OK, REVIEW_OK, FakeClient, _run

OUT_OF_PLAN = {"operations": [*CODER_OK["operations"],
                              {"path": "app/cart.py", "action": "update", "description": "tidy",
                               "search": "class Cart:", "replace": "class Cart:  # tidy"}]}


def _coder_payloads(client):
    return [json.loads(messages[-1]["content"]) for role, _, messages in client.calls if role == "Coder"]


def test_out_of_plan_edit_is_retried_without_a_model_review(make_repo):
    client = FakeClient(architect=ARCHITECT_OK, coder=[OUT_OF_PLAN, CODER_OK], reviewer=REVIEW_OK)
    result, _ = _run(make_repo, client)
    assert result.status == OutcomeStatus.AWAITING_APPROVAL, result.review
    assert [c[0] for c in client.calls] == ["Architect", "Coder", "Coder", "Reviewer"]
    repair = json.dumps(_coder_payloads(client)[1])
    assert "app/cart.py" in repair and "app/pricing.py" in repair


def test_coder_is_told_the_allowed_paths(make_repo):
    client = FakeClient(architect=ARCHITECT_OK, coder=CODER_OK, reviewer=REVIEW_OK)
    _run(make_repo, client)
    allowed = _coder_payloads(client)[0]["plan"]["allowed_paths"]
    assert "app/pricing.py" in allowed and "app/cart.py" not in allowed
