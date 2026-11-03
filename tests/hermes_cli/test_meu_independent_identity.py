"""Real startup/config paths must not recover a retired hosted identity."""

import json
import socket

import pytest

from hermes_cli.config_backend import write_config_document


@pytest.fixture
def offline_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    calls = []

    def no_network(_socket, address):
        calls.append(address)
        raise AssertionError(f"Unexpected connection: {address}")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    yield tmp_path
    assert calls == []


def test_stale_identity_does_not_override_direct_model(offline_home, monkeypatch):
    from hermes_cli.auth import resolve_provider
    from hermes_cli.runtime_provider import resolve_runtime_provider

    (offline_home / "auth.json").write_text(json.dumps({
        "version": 1, "active_provider": "nous",
        "providers": {"nous": {"access_token": "retired", "refresh_token": "retired"}},
    }), encoding="utf-8")
    write_config_document(offline_home / "config.yaml", {
        "model": {"provider": "deepseek", "default": "deepseek-v4-pro"},
    })
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-independent-key")
    assert resolve_provider("auto") == "deepseek"
    route = resolve_runtime_provider(requested="deepseek")
    assert route["provider"] == "deepseek"
    assert route["api_key"] == "test-independent-key"
    assert "api.deepseek.com" in route["base_url"]


def test_saved_hosted_settings_are_removed_and_catalog_is_offline(offline_home):
    from hermes_cli import config, model_catalog

    path = offline_home / "config.yaml"
    write_config_document(path, {
        "model": {"provider": "deepseek", "default": "deepseek-v4-pro"},
        "nous": {"anthropic_wire": "auto", "keepalive_interval_seconds": 10},
        "cron": {"provider": "chronos", "chronos": {"portal_url": "https://portal.nousresearch.com"}},
        "model_catalog": {"enabled": True, "url": "https://hermes-agent.nousresearch.com/docs/api/model-catalog.json"},
    })
    saved = config.load_config()
    assert "nous" not in saved
    assert "chronos" not in saved["cron"]
    assert saved["cron"]["provider"] == ""
    assert saved["model"]["provider"] == "deepseek"
    assert model_catalog.get_catalog(force_refresh=True) == {}
    assert "portal.nousresearch.com" not in path.read_text(encoding="utf-8")


def test_custom_catalog_is_preserved(offline_home):
    from hermes_cli.config import load_config

    write_config_document(offline_home / "config.yaml", {
        "model_catalog": {"url": "https://catalog.example/models.json"},
    })
    assert load_config()["model_catalog"]["url"] == "https://catalog.example/models.json"


def test_dashboard_and_remote_config_need_explicit_identity(offline_home, monkeypatch):
    from hermes_cli.dashboard_auth import list_interactive_providers
    from plugins.config_backends.remote.credentials import PlaneCredentialError, plane_token

    monkeypatch.delenv("GATEWAY_RELAY_IDP_TOKEN_URL", raising=False)
    assert all(p.name != "nous" for p in list_interactive_providers())
    with pytest.raises(PlaneCredentialError, match="explicit OAuth2"):
        plane_token(offline_home)


def test_skills_router_keeps_independent_registries(offline_home):
    from tools.skills_hub_search import create_source_router, _select_active_sources

    sources = create_source_router()
    active = {source.source_id() for source in _select_active_sources(sources, "all")}
    assert {"github", "clawhub", "skills-sh", "official"} <= active
    assert "hermes-index" not in active


def test_plugin_catalog_is_available_offline(offline_home):
    from hermes_cli.plugin_catalog import load_catalog, get_catalog_entry

    entries = load_catalog()
    assert entries
    assert get_catalog_entry(entries[0].name) == entries[0]


def test_conversation_affinity_restores_nested_scope(offline_home):
    from contextvars import Context
    from agent.conversation_affinity import (
        set_conversation_context, get_conversation_context, reset_conversation_context,
        set_affinity_scope, get_affinity_scope, reset_affinity_scope,
    )
    outer = set_conversation_context("parent")
    inner = set_conversation_context("child")
    scope = set_affinity_scope("profile-a")
    try:
        assert get_conversation_context() == "child"
        assert Context().run(get_conversation_context) is None
        reset_conversation_context(inner)
        assert get_conversation_context() == "parent"
        assert get_affinity_scope() == "profile-a"
    finally:
        reset_affinity_scope(scope)
        reset_conversation_context(outer)


@pytest.mark.parametrize("kind", ["skills", "plugins"])
def test_capabilities_catalog_is_local(offline_home, kind):
    from tui_gateway import server
    result = server.handle_request({"id": "catalog", "method": "capabilities.catalog", "params": {"kind": kind}})
    assert "error" not in result, result
    entries = result["result"]["entries"]
    assert entries
    assert all(row["name"] for row in entries)
