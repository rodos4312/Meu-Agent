"""Explicit task models are fixed; inherited/profile routing retains its own policy."""

from types import SimpleNamespace

import pytest

from tools.delegate_tool_tuning import pin_child_model


@pytest.mark.parametrize("model,profile,enabled", [("deepseek-flash", False, False),
                                                (None, False, True), ("deepseek-flash", True, True)])
def test_model_pin_respects_inherited_and_profile_auto(model, profile, enabled):
    policy = {"enabled": True, "another_policy_field": "retained"}
    child = SimpleNamespace(_model_routing_config=policy)
    pin_child_model(child, model, pin_model=not profile)
    assert child._model_routing_config == {"enabled": enabled, "another_policy_field": "retained"}
    assert policy["enabled"] is True
