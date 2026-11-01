"""Meu's fixed privacy policy across persistence, lifecycle hooks and the sender."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.request
from unittest.mock import Mock

import hermes_yaml as yaml
import pytest

from hermes_cli import config
from hermes_cli.config_backend import (
    Changes, FileBackend, write_changes, write_config_document, write_config_keys,
)
from hermes_cli.config_effective import load_user_config_effective
from hermes_cli.observability import relay_shared_metrics as relay
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_consent import consent_state, save_consent
from hermes_cli.observability.shared_metrics_events import record_setup_completed, record_slash_command
from hermes_cli.observability.shared_metrics_send_config import resolve_send_config
from hermes_cli.observability.shared_metrics_sender import SharedMetricsSender, _post


LEGACY = {
    "model": {"provider": "deepseek", "default": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1"},
    "memory": {"enabled": True},
    "telemetry": {"shared_metrics": {
        "enabled": True, "send": True, "endpoint": "https://telemetry.nousresearch.com/v1/telemetry",
    }},
}


def _read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _assert_private(raw):
    shared = raw["telemetry"]["shared_metrics"]
    assert shared["enabled"] is False
    assert shared["send"] is False
    assert shared["endpoint"] == ""
    assert consent_state(raw) == {"enabled": False, "send": False, "decided": True, "reask": False}


@pytest.mark.parametrize("answer", [None, {}, LEGACY, {"telemetry": {"shared_metrics": {"enabled": False}}}])
def test_no_config_or_legacy_answer_can_enable_collection_or_sending(answer, monkeypatch):
    monkeypatch.setattr(config, "read_raw_config_readonly", lambda: answer)
    resolved = resolve_send_config(answer)
    assert (resolved.enabled, resolved.send, resolved.endpoint) == (False, False, "")
    assert relay.enabled() is False
    assert consent_state(answer) == {"enabled": False, "send": False, "decided": True, "reask": False}


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


@pytest.mark.parametrize("writer", ["document", "keys", "changes", "save", "consent", "unset"])
def test_every_writer_persists_off_even_when_requested_on(tmp_path, monkeypatch, writer):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path.write_text(yaml.safe_dump(LEGACY), encoding="utf-8")
    writers = {
        "document": lambda: write_config_document(path, LEGACY),
        "keys": lambda: write_config_keys(path, {
            "telemetry.shared_metrics.enabled": True, "telemetry.shared_metrics.send": True}),
        "changes": lambda: write_changes(path, Changes(set={"telemetry": LEGACY["telemetry"]})),
        "save": lambda: config.save_config(config.load_config()),
        "consent": lambda: save_consent(True, True),
        "unset": lambda: write_config_keys(path, {"telemetry": None}),
    }
    writers[writer]()
    stored = _read(path)
    _assert_private(stored)
    assert stored["model"] == LEGACY["model"]
    assert stored["memory"] == LEGACY["memory"]
    _assert_private(config.load_config())
    _assert_private(load_user_config_effective(path))


def test_manual_legacy_file_is_ignored_by_effective_loaders(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(LEGACY), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _assert_private(config.load_config())
    _assert_private(load_user_config_effective(path))


def test_opt_out_survives_restart_and_new_attempted_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    write_config_document(tmp_path / "config.yaml", LEGACY)
    code = (
        "import json; from hermes_cli.config import load_config; "
        "from hermes_cli.observability.shared_metrics_consent import save_consent; "
        "save_consent(True, True); print(json.dumps(load_config()))"
    )
    stored = json.loads(subprocess.check_output([sys.executable, "-c", code], env=dict(os.environ), text=True))
    _assert_private(stored)
    _assert_private(_read(tmp_path / "config.yaml"))
    assert stored["model"]["provider"] == "deepseek"


@pytest.mark.parametrize("source", ["managed", "worker"])
def test_overlays_and_worker_snapshots_cannot_reenable_metrics(tmp_path, monkeypatch, source):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    if source == "managed":
        monkeypatch.setattr(config.managed_scope, "load_managed_config", lambda: LEGACY)
    else:
        monkeypatch.setattr(config, "_worker_config_snapshot", lambda: LEGACY)
    _assert_private(config.load_config())


def test_hooks_neither_collect_nor_attempt_network_with_legacy_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(LEGACY), encoding="utf-8")
    connect = Mock(side_effect=AssertionError("Unexpected outbound telemetry"))
    urlopen = Mock(side_effect=AssertionError("Unexpected telemetry POST"))
    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    record_setup_completed(surface="desktop", provider="deepseek")
    record_slash_command(command="help", surface="cli")
    relay.observe_lifecycle("on_session_start", session_id="privacy-test")
    relay.observe_lifecycle("on_session_end", session_id="privacy-test")
    relay.shutdown_runtimes()
    assert not (tmp_path / "telemetry").exists()
    connect.assert_not_called()
    urlopen.assert_not_called()


@pytest.mark.parametrize("endpoint", ["https://telemetry.nousresearch.com/v1/telemetry", "http://127.0.0.1:9876/metrics"])
def test_legacy_outbox_and_injected_transport_cannot_send(tmp_path, monkeypatch, endpoint):
    store = SharedMetricsStore(database_path=tmp_path / "metrics.sqlite3", outbox_directory=tmp_path / "outbox")
    payload = {"package_id": "legacy", "metrics": [{"name": "hermes.client.active", "value": 1}]}
    with store._connection() as connection:
        connection.execute(
            "INSERT INTO send_consent_windows(opened_at, last_confirmed_at) VALUES (?, ?)",
            ("2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z"),
        )
        connection.execute(
            "INSERT INTO package_outbox(package_id, period_start, period_end, payload_json, created_at, exported_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy", "2026-10-01T00:00:00Z", "2026-10-01T23:59:59Z", json.dumps(payload),
             "2026-10-02T00:00:00Z", "2026-10-02T00:00:00Z"),
        )
    post = Mock(side_effect=AssertionError("Injected transports must also stay disabled"))
    urlopen = Mock(side_effect=AssertionError("Unexpected network"))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    for check in (None, lambda: True):
        sender = SharedMetricsSender(store, endpoint, post=post, consent_check=check)
        assert sender.send_pending().sent == 0
    with pytest.raises(PermissionError):
        _post(endpoint, b"{}", timeout=1)
    post.assert_not_called()
    urlopen.assert_not_called()
    with store._connection() as connection:
        assert connection.execute("SELECT sent_at FROM package_outbox").fetchone()[0] is None
