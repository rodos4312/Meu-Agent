"""Meu must prevent grandchildren even when delegation config requests deeper nesting."""

from types import SimpleNamespace

import pytest

from agent.subagent_lifecycle import SubagentLifecycleError, SubagentLifecycleService
from tools import delegate_tool_config


def test_meu_flattens_configured_delegation(monkeypatch):
    monkeypatch.setenv("MEU_AGENT_MODE", "1")
    monkeypatch.setattr(delegate_tool_config, "_cfg", lambda: {"max_spawn_depth": 99})
    assert delegate_tool_config._get_max_spawn_depth() == 1


def test_other_runtime_can_keep_its_configured_depth(monkeypatch):
    monkeypatch.delenv("MEU_AGENT_MODE", raising=False)
    monkeypatch.setattr(delegate_tool_config, "_cfg", lambda: {"max_spawn_depth": 3})
    assert delegate_tool_config._get_max_spawn_depth() == 3


def test_meu_leaf_cannot_spawn_via_lifecycle_plugin(monkeypatch):
    monkeypatch.setenv("MEU_AGENT_MODE", "1")
    service = SubagentLifecycleService(lambda: SimpleNamespace(_delegate_depth=1, session_id="child"))
    with pytest.raises(SubagentLifecycleError, match="depth limit"):
        service.launch({"goal": "Try to launch a forbidden grandchild"})
