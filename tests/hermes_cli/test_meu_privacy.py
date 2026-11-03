"""Legacy opt-ins cannot recreate the removed collector; plugin lifecycle remains usable."""

import importlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import urllib.request
from unittest.mock import Mock

import hermes_yaml as yaml
import pytest

from hermes_cli import config, lifecycle, plugins
from hermes_cli.config_backend import Changes, FileBackend, write_changes, write_config_document, write_config_keys
from hermes_cli.config_effective import load_user_config_effective
from hermes_cli.meu_privacy import strip_retired_settings


LEGACY = {
    "model": {"provider": "deepseek", "default": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1"},
    "memory": {"enabled": True},
    "nous": {"keepalive_interval_seconds": 900},
    "telemetry": {"shared_metrics": {
        "enabled": True, "send": True, "endpoint": "https://telemetry.nousresearch.com/v1/telemetry",
    }},
}


def _read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _assert_private(raw):
    assert "shared_metrics" not in (raw.get("telemetry") or {})
    assert "keepalive_interval_seconds" not in (raw.get("nous") or {})


@pytest.mark.parametrize("document", [{}, LEGACY, {"telemetry": {"shared_metrics": {"enabled": False}}}])
def test_retired_settings_are_removed_without_mutating_input(document):
    before = json.dumps(document)
    cleaned = strip_retired_settings(document)
    _assert_private(cleaned)
    assert json.dumps(document) == before
    assert strip_retired_settings(cleaned) == cleaned


def test_other_telemetry_settings_are_not_erased():
    cleaned = strip_retired_settings({"telemetry": {"plugin_option": 3, "shared_metrics": {"enabled": True}}})
    assert cleaned == {"telemetry": {"plugin_option": 3}}


def test_boot_migrates_legacy_opt_in_and_keeps_deepseek_and_memory(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("# Keep my settings\n" + yaml.safe_dump(LEGACY), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    FileBackend().boot(tmp_path)
    stored = _read(path)
    _assert_private(stored)
    assert stored["model"] == LEGACY["model"]
    assert stored["memory"] == LEGACY["memory"]
    assert "# Keep my settings" in path.read_text(encoding="utf-8")
    before = path.read_bytes()
    FileBackend().boot(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("writer", ["document", "keys", "changes", "save", "unset"])
def test_every_writer_removes_legacy_settings(tmp_path, monkeypatch, writer):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path.write_text(yaml.safe_dump(LEGACY), encoding="utf-8")
    writers = {
        "document": lambda: write_config_document(path, LEGACY),
        "keys": lambda: write_config_keys(path, {
            "telemetry.shared_metrics.enabled": True, "telemetry.shared_metrics.send": True,
            "nous.keepalive_interval_seconds": 5}),
        "changes": lambda: write_changes(path, Changes(set={"telemetry": LEGACY["telemetry"], "nous": LEGACY["nous"]})),
        "save": lambda: config.save_config(config.load_config()),
        "unset": lambda: write_config_keys(path, {"telemetry": None}),
    }
    writers[writer]()
    stored = _read(path)
    _assert_private(stored)
    assert stored["model"] == LEGACY["model"]
    assert stored["memory"] == LEGACY["memory"]
    _assert_private(config.load_config())
    _assert_private(load_user_config_effective(path))


def test_migration_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_config_document(tmp_path / "config.yaml", LEGACY)
    code = "import json; from hermes_cli.config import load_config; print(json.dumps(load_config()))"
    stored = json.loads(subprocess.check_output([sys.executable, "-c", code], env=dict(os.environ), text=True))
    _assert_private(stored)
    assert stored["model"]["provider"] == "deepseek"


@pytest.mark.parametrize("source", ["managed", "worker"])
def test_overlays_and_worker_snapshots_drop_retired_settings(tmp_path, monkeypatch, source):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    if source == "managed":
        monkeypatch.setattr(config.managed_scope, "load_managed_config", lambda: LEGACY)
    else:
        monkeypatch.setattr(config, "_worker_config_snapshot", lambda: LEGACY)
    _assert_private(config.load_config())


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


def test_effective_config_removes_keepalive_without_a_telemetry_section(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"nous": {"keepalive_interval_seconds": 5, "other": 1}}), encoding="utf-8")
    effective = load_user_config_effective(path)
    _assert_private(effective)
    assert effective["nous"]["other"] == 1
