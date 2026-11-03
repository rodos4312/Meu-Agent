"""Removed telemetry RPCs cannot collect events or change profile settings."""

import socket

import pytest

from tui_gateway import contracts, server


@pytest.mark.parametrize("method,params", [
    ("diagnostics.share_nous", {"error_context": "private local error", "extra_files": {"desktop.log": "private"}}),
    ("shared_metrics.status", {}),
    ("shared_metrics.set", {"enabled": True, "send": True, "first_run": True}),
    ("shared_metrics.slash_command", {"command": "skills"}),
    ("shared_metrics.startup_latency", {"elapsed_ms": 120, "surface": "desktop_attach"}),
    ("shared_metrics.update_run", {"outcome": "success"}),
    ("shared_metrics.desktop_feature_use", {"area": "settings_model"}),
    ("shared_metrics.desktop_friction", {"kind": "error_toast", "detail": "other"}),
    ("shared_metrics.desktop_onboarding", {"step": "welcome", "event": "completed"}),
    ("shared_metrics.desktop_dislike", {"signal": "quick_close"}),
    ("shared_metrics.desktop_daily", {"day": "2026-11-03"}),
])
def test_retired_metrics_method_is_unknown_without_network_or_profile_changes(method, params, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text("model:\n  provider: deepseek\n", encoding="utf-8")
    before = config.read_bytes()
    attempts = []

    def connect(_socket, address):
        attempts.append(address)
        raise AssertionError(f"Unexpected telemetry connection: {address}")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(server, "_hermes_home", tmp_path)
    monkeypatch.setattr(socket.socket, "connect", connect)
    reply = server.handle_request({"jsonrpc": "2.0", "id": "retired", "method": method, "params": params})
    assert reply["error"]["code"] == -32601
    assert method not in contracts.METHODS
    assert config.read_bytes() == before
    assert not (tmp_path / "telemetry").exists()
    assert attempts == []
