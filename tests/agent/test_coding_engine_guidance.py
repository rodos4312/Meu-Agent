"""Capability-aware startup routing without a second router or mutable prefix."""
from types import SimpleNamespace

from agent.coding_engine_guidance import CODING_ENGINE_GUIDANCE
from agent.coding_context import resolve_runtime_mode
from agent.system_prompt import _tool_guidance_block


def test_general_chat_gets_engine_routing_when_capability_is_available():
    agent = SimpleNamespace(valid_tool_names={"coding_task", "terminal"})
    brief = _tool_guidance_block(agent)
    assert CODING_ENGINE_GUIDANCE in brief
    assert "coding_task(action='start'" in brief
    assert "automatically" in brief and "small programs" in brief
    assert "fingerprint-bound approval" in brief
    assert _tool_guidance_block(agent) == brief


def test_disabled_engine_is_never_advertised():
    assert _tool_guidance_block(SimpleNamespace(valid_tool_names={"terminal"})) is None
    assert _tool_guidance_block(SimpleNamespace(valid_tool_names=set())) is None


def test_code_workspace_does_not_get_conflicting_direct_edit_instructions(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='example'\n")
    mode = resolve_runtime_mode(platform="desktop", cwd=tmp_path, config={})
    assert mode.is_coding
    engine = mode.system_prompt_parts(valid_tool_names={"coding_task", "terminal"}, workspace_block="pinned")
    assert engine[0] == [] and engine[1] == ["pinned"]
    ordinary = mode.system_prompt_parts(valid_tool_names={"terminal", "patch"}, workspace_block="pinned")
    assert "Edit with `patch`/`write_file`" in ordinary[0][0]
    assert engine == mode.system_prompt_parts(valid_tool_names={"coding_task", "terminal"}, workspace_block="pinned")


def test_real_catalog_points_competing_tools_to_engine_only_when_enabled():
    from model_tools import _apply_dynamic_schemas
    from tools.registry import registry
    # Real registered schemas, so the test exercises the actual catalog assembly seam.
    names = ["terminal", "read_file", "write_file", "patch", "coding_task"]
    definitions = registry.get_definitions(names, quiet=True)
    assert {d["function"]["name"] for d in definitions} == set(names)
    routed = _apply_dynamic_schemas(definitions)
    for schema in routed:
        if schema["function"]["name"] != "coding_task":
            assert schema["function"]["description"].startswith("DEVELOPMENT REQUESTS: first call coding_task")
    assert definitions == registry.get_definitions(names, quiet=True)  # no global schema mutation
    ordinary = [d for d in definitions if d["function"]["name"] != "coding_task"]
    assert _apply_dynamic_schemas(ordinary) == ordinary
