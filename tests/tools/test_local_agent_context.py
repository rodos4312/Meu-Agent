"""Live agent context is explicit local opt-in, never an incidental transport kwarg."""
import json
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("kind", ["local", "host", "generic"])
def test_model_tool_dispatch_only_gives_live_context_to_explicit_local_handlers(monkeypatch, kind):
    import model_tools
    from tools.registry import ToolRegistry
    registry = ToolRegistry()
    agent = SimpleNamespace(session_id="parent")
    received = []

    def handler(args, *, parent_agent=None, **kwargs):
        received.append(parent_agent)
        return json.dumps({"ok": True})

    def generic(args, **kwargs):
        assert "parent_agent" not in kwargs
        received.append(None)
        return json.dumps({"ok": True})

    if kind == "host":
        handler.__hermes_plugin_host_ref__ = 1
    registry.register(name="local_context_fixture", toolset="fixture", schema={"name": "local_context_fixture"},
                      handler=generic if kind == "generic" else handler)
    monkeypatch.setattr(model_tools, "registry", registry)
    result = model_tools.handle_function_call("local_context_fixture", {}, parent_agent=agent,
                                             skip_pre_tool_call_hook=True, skip_tool_execution_middleware=True)
    assert json.loads(result) == {"ok": True}
    assert received == [agent if kind == "local" else None]
