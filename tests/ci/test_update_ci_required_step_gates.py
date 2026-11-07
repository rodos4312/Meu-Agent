"""A disabled or advisory required workflow step must make replay fail."""
import pytest

from tests.ci import test_update_ci_routing as routing


@pytest.mark.platforms("linux", "windows")
@routing._EMULATED_BASH
@pytest.mark.parametrize("lane,rel,job,name", routing._REQUIRED_STEP_CASES)
@pytest.mark.parametrize("mutation", ["disabled", "advisory"])
def test_replay_rejects_ineffective_required_step(
    monkeypatch, valid_update_workflow_consumers, lane, rel, job, name, mutation
):
    routing.assert_ineffective_required_step(monkeypatch, lane, rel, job, name, mutation)
