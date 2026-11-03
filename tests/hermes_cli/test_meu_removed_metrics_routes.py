"""The real web application no longer exposes telemetry consent controls."""

import socket

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("method, status", [("GET", 404), ("PUT", 405)])
def test_retired_consent_route_is_missing_without_profile_changes(method, status, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import web_server

    config = tmp_path / "config.yaml"
    config.write_text("model:\n  provider: deepseek\n", encoding="utf-8")
    before = config.read_bytes()
    attempts = []
    connect = socket.socket.connect

    def refuse_network(sock, address):
        # Windows asyncio uses loopback for its event-loop wakeup.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return connect(sock, address)
        attempts.append(address)
        raise AssertionError(f"Unexpected connection: {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    response = client.request(
        method, "/api/shared-metrics/consent", json={"enabled": True, "send": True},
    )
    # The SPA fallback handles GET only; PUT reaches its method-not-allowed response.
    assert response.status_code == status
    assert not any(getattr(route, "path", None) == "/api/shared-metrics/consent"
                   for route in web_server.app.routes)
    assert config.read_bytes() == before
    assert not (tmp_path / "telemetry").exists()
    assert attempts == []
