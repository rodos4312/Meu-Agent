"""Removed telemetry stays absent; plugin lifecycle remains available without network."""
import importlib
import socket
import sqlite3
import urllib.request
from unittest.mock import Mock

import hermes_yaml as yaml
import pytest

from hermes_cli import lifecycle, plugins

# Hooks do not reactivate an obsolete collector even if a file still contains old opt-ins.
LEGACY = {"telemetry": {"shared_metrics": {"enabled": True, "send": True}}}

def test_keys_catalog_lists_direct_search_and_omits_retired_services(monkeypatch, tmp_path):
    from hermes_cli.web_routers.config_env import _get_env_vars_sync

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    entries = _get_env_vars_sync()
    assert entries["FIRECRAWL_API_KEY"]["category"] == "tool"
    assert entries["DEEPSEEK_API_KEY"]["provider"] == "deepseek"
    assert not {
        "HERMES_ANON_API_SECRET", "FIRECRAWL_GATEWAY_URL", "TOOL_GATEWAY_URL",
        "CONNECTOR_GATEWAY_URL", "TOOL_GATEWAY_DOMAIN", "TOOL_GATEWAY_SCHEME", "TOOL_GATEWAY_USER_TOKEN",
    }.intersection(entries)


@pytest.mark.parametrize("legacy_outbox", [False, True])
def test_lifecycle_keeps_plugins_without_network_or_collector_files(tmp_path, monkeypatch, legacy_outbox):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(LEGACY), encoding="utf-8")
    outbox = tmp_path / "telemetry" / "shared_metrics" / "metrics.sqlite3"
    if legacy_outbox:
        outbox.parent.mkdir(parents=True)
        connection = sqlite3.connect(outbox)
        try:
            connection.execute("CREATE TABLE package_outbox (package_id TEXT, payload TEXT)")
            connection.execute("INSERT INTO package_outbox VALUES (?, ?)", ("legacy", '{"pending": true}'))
            connection.commit()
        finally:
            connection.close()
        before = outbox.read_bytes()
    connect = Mock(side_effect=AssertionError("Unexpected network"))
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(urllib.request, "urlopen", connect)
    hook = Mock(return_value=["plugin result"])
    monkeypatch.setattr(plugins, "invoke_hook", hook)
    monkeypatch.setattr(plugins, "has_hook", lambda name: name == "on_session_start")
    assert lifecycle.has_hook("on_session_start")
    assert lifecycle.invoke_hook("on_session_start", session_id="local-test") == ["plugin result"]
    assert lifecycle.invoke_hook("on_session_end", session_id="local-test") == ["plugin result"]
    assert hook.call_count == 2
    if legacy_outbox:
        assert outbox.read_bytes() == before
    else:
        assert not (tmp_path / "telemetry").exists()
    connect.assert_not_called()


@pytest.mark.parametrize("module", [
    "shared_metrics", "shared_metrics_sender", "shared_metrics_consent", "shared_metrics_events",
    "relay_shared_metrics", "shared_metrics_process", "shared_metrics_update",
])
def test_removed_collector_has_no_callable_entry_point(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("hermes_cli.observability." + module)
