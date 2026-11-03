"""Independent tool discovery and MCP setup must not create a Nous account or send HTTP."""

import json
import socket

import httpx
import pytest
import requests


@pytest.fixture
def no_outbound(monkeypatch):
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Unexpected outbound request during local discovery")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(requests.Session, "send", refuse)
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    yield
    # Catch callers that swallow transport failures as well as propagated failures.
    assert attempts == []


def test_mcp_search_describe_and_dispatch_stay_local(no_outbound):
    import model_tools
    from tools.registry import registry
    from tools.tool_search import dispatch_tool_describe, dispatch_tool_search

    name = "mcp_meu_fixture_find_notes"
    schema = {
        "name": name,
        "description": "Find notes in the local notebook",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    }
    registry.register(
        name=name,
        toolset="mcp-meu-fixture",
        schema=schema,
        handler=lambda args, **kw: json.dumps({"notes": [args["query"]]}),
    )
    try:
        definitions = [{"type": "function", "function": schema}]
        found = json.loads(
            dispatch_tool_search(
                {"queries": ["find notes"]}, current_tool_defs=definitions
            )
        )
        assert name in found["tools"]
        described = json.loads(
            dispatch_tool_describe({"names": [name]}, current_tool_defs=definitions)
        )
        assert described["tools"][name]["parameters"] == schema["parameters"]
        result = json.loads(
            model_tools.handle_function_call(
                name, {"query": "a saved note"}, enabled_toolsets=["mcp-meu-fixture"]
            )
        )
        assert result == {"notes": ["a saved note"]}
    finally:
        with registry._lock:
            registry._tools.pop(name, None)
            registry._generation += 1


def test_unknown_mcp_entry_never_falls_back_to_a_hosted_account(no_outbound):
    from tools.connectors.tool import manage_connections
    from hermes_cli.auth import _load_auth_store
    from tools.setup_beat_tool import _connected, _connector_slugs

    before = _load_auth_store()
    result = json.loads(
        manage_connections(
            {"action": "install", "connectors": ["meu-nonexistent-entry"]}
        )
    )
    assert "error" in result and "meu-nonexistent-entry" in result["error"]
    assert _connected() == {"connected": []}
    assert _connector_slugs()
    assert _load_auth_store() == before


def test_connector_preference_persists_without_account_access(
    tmp_path, monkeypatch, no_outbound
):
    from tools.connectors.config import connectors_available
    from hermes_cli.config import load_config, save_config

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = load_config()
    config.setdefault("tools", {})["connectors"] = {"enabled": False}
    save_config(config)
    assert not connectors_available()
    config = load_config()
    config["tools"]["connectors"] = {"enabled": True}
    save_config(config)
    assert connectors_available()
