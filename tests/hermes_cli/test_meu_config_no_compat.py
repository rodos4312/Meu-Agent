"""Retired service configuration is rejected, never migrated or silently rerouted."""
import json
from unittest.mock import Mock

import hermes_yaml as yaml
import pytest

from hermes_cli import config
from hermes_cli.config_backend import (
    Changes, ConfigBackendUnavailable, ConfigValueError, FileBackend,
    write_changes, write_config_document, write_config_keys,
)
from hermes_cli.config_effective import load_user_config_effective

RETIRED = [
    {"nous": {"other": 1}},
    {"telemetry": {"shared_metrics": {"enabled": False}}},
    {"dashboard": {"oauth": {"client_id": "old"}}},
    {"display": {"credits_notices": False}},
    {"cron": {"chronos": {}}},
    {"cron": {"provider": "chronos"}},
    {"model": {"provider": "nous"}},
    {"auxiliary": {"review": {"provider": "solstice"}}},
    {"browser": {"cloud_provider": "nous"}},
    {"browser": {"backend": "nous"}},
    {"web": {"use_gateway": False}},
    {"fallback_model": [{"provider": "nous", "model": "old"}]},
    {"providers": {"nous": {"enabled": False}}},
    {"terminal": {"modal_mode": "managed"}},
    {"custom_providers": [{"name": "nous", "base_url": "https://example.test"}]},
    {"model_catalog": {"url": "https://portal.nousresearch.com/models"}},
    {"model": {"base_url": "https://inference-api.nousresearch.com/v1"}},
]

@pytest.mark.parametrize("document", RETIRED)
@pytest.mark.parametrize("loader", [config.load_config, config.load_config_readonly, load_user_config_effective])
def test_retired_config_is_rejected_without_rewriting_or_network(tmp_path, monkeypatch, document, loader):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text("# User settings stay untouched\n" + yaml.safe_dump(document), encoding="utf-8")
    before = path.read_bytes()
    network = Mock(side_effect=AssertionError("Unexpected network"))
    monkeypatch.setattr("socket.socket.connect", network)
    FileBackend().boot(tmp_path)
    with pytest.raises(ConfigBackendUnavailable, match="not supported"):
        loader()
    assert path.read_bytes() == before
    network.assert_not_called()

@pytest.mark.parametrize("changes", [
    Changes(document={"nous": {"anything": 1}}),
    Changes(set={"nous.anything": 1, "memory.enabled": False}),
    Changes(set={"telemetry.shared_metrics.enabled": True}),
    Changes(set={"model_catalog.providers.custom.url": "https://portal.nousresearch.com/catalog"}),
    Changes(set={"fallback_model": [{"provider": "nous"}]}),
])
def test_rejected_write_is_all_or_nothing(tmp_path, monkeypatch, changes):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    write_config_document(path, {"memory": {"enabled": True}})
    before = path.read_bytes()
    with pytest.raises(ConfigValueError, match="not supported"):
        write_changes(path, changes)
    assert path.read_bytes() == before


def test_no_implicit_cleanup_but_explicit_removal_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"nous": {"old": 1}, "memory": {"enabled": True}}), encoding="utf-8")
    write_config_keys(path, {"display.show_cost": True})
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["nous"] == {"old": 1}
    write_config_keys(path, {"nous": None})
    assert config.load_config()["memory"]["enabled"] is True

@pytest.mark.parametrize("source", ["managed", "worker"])
def test_overlay_and_worker_snapshot_are_not_migrated(tmp_path, monkeypatch, source):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    if source == "managed":
        monkeypatch.setattr(config.managed_scope, "load_managed_config", lambda: {"nous": {}})
    else:
        monkeypatch.setattr(config, "_worker_config_snapshot", lambda: {"nous": {}})
    with pytest.raises(ConfigBackendUnavailable, match="not supported"):
        config.load_config()


def test_supported_document_round_trips_without_conversion(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    document = {"model": {"provider": "deepseek", "default": "test-model"},
                "memory": {"enabled": True}, "telemetry": {"plugin_option": 3},
                "mcp_servers": {"local": {"command": "test-mcp"}}}
    original = json.dumps(document)
    write_config_document(tmp_path / "config.yaml", document)
    loaded = config.load_config()
    for section, values in document.items():
        for key, value in values.items():
            assert loaded[section][key] == value
    assert json.dumps(document) == original


def test_error_does_not_echo_obsolete_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    secret = "test-only-obsolete-credential"
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"nous": {"api_key": secret}}), encoding="utf-8")
    with pytest.raises(ConfigBackendUnavailable) as error:
        config.load_config()
    assert secret not in str(error.value)


def test_rejection_survives_a_fresh_process(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text("nous: {}\n", encoding="utf-8")
    before = path.read_bytes()
    result = subprocess.run([sys.executable, "-c", "from hermes_cli.config import load_config; load_config()"],
                            env=dict(os.environ), text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "not supported" in result.stderr
    assert path.read_bytes() == before


def test_offline_provider_fixture_has_no_retired_settings(tmp_path, monkeypatch):
    from tests.fakes.fake_llm_provider import write_hermes_home

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_hermes_home(tmp_path, "http://127.0.0.1:9999/v1")
    loaded = config.load_config()
    assert loaded["model"]["provider"] == "custom"
    assert loaded["model"]["base_url"] == "http://127.0.0.1:9999/v1"
    assert "shared_metrics" not in loaded.get("telemetry", {})


@pytest.mark.parametrize("surface", ["log", "secret_file"])
def test_obsolete_key_is_still_masked_in_output(monkeypatch, surface):
    from agent import redact

    monkeypatch.setattr(redact, "_REDACT_ENABLED", True)
    secret = "obsolete-test-only-credential-0123456789"
    output = redact.redact_sensitive_text(f"NOUS_API_KEY={secret}\nstatus=offline", force=True, file_read=surface == "secret_file", secret_file=surface == "secret_file")
    assert secret not in output
    assert "status=offline" in output


def test_live_canary_does_not_read_obsolete_credentials(monkeypatch):
    import importlib
    from tests.e2e.core.live import _helpers

    monkeypatch.setenv("NOUS_API_KEY", "obsolete-test-only")
    monkeypatch.setenv("OPENAI_API_KEY", "supported-test-only")
    helpers = importlib.reload(_helpers)
    assert "NOUS_API_KEY" not in helpers._LIVE_KEYS
    assert helpers._LIVE_KEYS["OPENAI_API_KEY"] == "supported-test-only"
