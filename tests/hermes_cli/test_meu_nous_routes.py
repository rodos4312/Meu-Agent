"""Removed Nous providers have no catalog, login or account-handoff entry points."""

import contextvars
import socket
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli.web_routers import oauth


@pytest.fixture
def offline_routes(monkeypatch):
    attempts = []
    connect = socket.socket.connect

    def refuse_network(_socket, address):
        # Windows asyncio uses a loopback socket pair for its event-loop wakeup.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return connect(_socket, address)
        attempts.append(address)
        raise AssertionError(f"Unexpected network connection: {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(oauth, "_require_token", lambda _request: None)
    app = FastAPI()
    app.include_router(oauth.router)
    with TestClient(app) as client:
        yield client
    assert attempts == []


def test_real_catalog_has_no_nous_account_or_provider(offline_routes):
    from hermes_cli.auth import PROVIDER_REGISTRY
    from hermes_cli.provider_catalog import provider_catalog
    from providers import get_provider_profile

    response = offline_routes.get("/api/providers/oauth")
    assert response.status_code == 200
    accounts = {provider["id"] for provider in response.json()["providers"]}
    assert "nous" not in accounts
    assert "solstice" not in accounts
    assert "openai-codex" in accounts
    assert "nous" not in PROVIDER_REGISTRY
    assert get_provider_profile("nous") is None
    assert get_provider_profile("solstice") is None
    catalog = {provider.slug: provider for provider in provider_catalog()}
    assert "nous" not in catalog
    assert catalog["deepseek"].api_key_env_vars == ("DEEPSEEK_API_KEY",)


def test_retired_login_is_unknown_and_handoff_route_does_not_exist(offline_routes):
    response = offline_routes.post("/api/providers/oauth/nous/start", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown provider nous"
    assert offline_routes.get("/api/providers/oauth/nous/handoff").status_code == 404


def test_supported_device_login_keeps_its_dispatch(offline_routes, monkeypatch):
    calls = []

    async def start(provider_id, profile=None):
        calls.append((provider_id, profile))
        return {"session_id": "supported-login", "flow": "device_code"}

    monkeypatch.setattr(oauth, "_start_device_code_flow", start)
    response = offline_routes.post("/api/providers/oauth/openai-codex/start", json={})
    assert response.status_code == 200
    assert response.json()["session_id"] == "supported-login"
    assert calls == [("openai-codex", None)]


def test_supported_device_poller_keeps_the_request_context():
    owner = contextvars.ContextVar("oauth_test_owner", default="launch")
    finished = threading.Event()
    calls = []

    def poll(session_id):
        calls.append((session_id, owner.get()))
        finished.set()

    token = owner.set("secondary-profile")
    try:
        oauth._start_poller(poll, "supported-session")
    finally:
        owner.reset(token)
    assert finished.wait(3)
    assert calls == [("supported-session", "secondary-profile")]
    assert owner.get() == "launch"
