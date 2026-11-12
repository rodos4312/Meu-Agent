"""Unit tests for boot-time relay self-provisioning.

Covers gateway.relay.self_provision_relay() + the relay_endpoint() /
relay_route_keys() config readers. The connector HTTP POST is monkeypatched
(the cross-repo E2E exercises the real /relay/provision); these prove the
TRIGGER logic, in-process env wiring, and fail-soft boot behaviour.

The trigger is deliberately NOT is_managed() (that means NixOS/package-manager-
managed, which is False on a NAS-hosted Fly agent). The real gate is
"relay_url set + no pinned secret + a resolvable NAS token".
"""

from __future__ import annotations

import json
import logging
import os

import pytest

from agent import secret_scope
from gateway import relay
from gateway.run_startup import GatewayStartupMixin


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in (
        "GATEWAY_RELAY_URL",
        "GATEWAY_RELAY_ID",
        "GATEWAY_RELAY_SECRET",
        "GATEWAY_RELAY_DELIVERY_KEY",
        "GATEWAY_RELAY_ENDPOINT",
        "GATEWAY_RELAY_ROUTE_KEYS",
        "GATEWAY_RELAY_PLATFORM",
        "GATEWAY_RELAY_BOT_ID",
        "GATEWAY_RELAY_INSTANCE_ID",
        "GATEWAY_RELAY_WAKE_URL",
    ):
        monkeypatch.delenv(k, raising=False)
    # Never read config.yaml off disk in these tests.
    monkeypatch.setattr("gateway.run._load_gateway_config", dict, raising=False)


def _stub_post(captured: dict):
    """A fake _post_provision that records its kwargs and returns creds."""

    def _fake(**kwargs):
        captured.update(kwargs)
        return {
            "secret": "a" * 64,
            "deliveryKey": "b" * 64,
            "tenant": "org-tenant-x",
            "gatewayId": kwargs["gateway_id"],
            "routeKeys": kwargs["route_keys"],
        }

    return _fake


def _arm(monkeypatch, *, url="wss://connector.example/relay", token="nas-token"):
    """Arm the real trigger: a relay URL + a resolvable NAS token.

    Note there is intentionally no `managed` knob — self-provision no longer
    consults is_managed(). A test that wants the "no NAS identity" branch
    monkeypatches resolve_nous_access_token to raise instead.
    """
    monkeypatch.setattr(relay, "relay_url", lambda: url)
    monkeypatch.setattr("hermes_cli.auth.resolve_nous_access_token", lambda: token)


# ─────────────────────────── config readers ───────────────────────────


def test_provision_url_maps_ws_to_http():
    assert relay._provision_url("wss://c.example/relay") == "https://c.example/relay/provision"
    assert relay._provision_url("ws://c.example/relay") == "http://c.example/relay/provision"
    assert relay._provision_url("https://c.example") == "https://c.example/relay/provision"


# ─────────────────────────── trigger logic ───────────────────────────


# ─────────────────────────── happy path ───────────────────────────

# ─────────────────── instance-id forwarding (Phase 6 Unit α) ───────────────────




def test_post_provision_body_includes_instanceId_only_when_set(monkeypatch):
    """The real _post_provision adds `instanceId` to the JSON body ONLY when a
    value is supplied — omitting it lets the connector store null (back-compat),
    rather than binding an empty string."""
    import json

    sent: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"secret": "a" * 64, "deliveryKey": "b" * 64, "tenant": "t", "gatewayId": "gw-1"}).encode()

    def _fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    # With an instance id -> present in the body.
    relay._post_provision(
        provision_url="https://c.example/relay/provision",
        access_token="tok",
        gateway_id="gw-1",
        platform="discord",
        bot_id="app",
        gateway_endpoint=None,
        route_keys=[],
        instance_id="inst-abc",
    )
    assert sent["body"]["instanceId"] == "inst-abc"

    # Without one -> the key is absent entirely (not "" ).
    relay._post_provision(
        provision_url="https://c.example/relay/provision",
        access_token="tok",
        gateway_id="gw-1",
        platform="discord",
        bot_id="app",
        gateway_endpoint=None,
        route_keys=[],
    )
    assert "instanceId" not in sent["body"]


# ─────────────────── wake-url forwarding (Phase 5 Unit C) ───────────────────


# ─────────────────────────── fail-soft ───────────────────────────

# ─────────────────────────── displayName (Phase 1 parity, gg#171) ───────────────────────────


def test_relay_display_name_suppresses_stock_brand(monkeypatch):
    """The default 'Hermes Agent' brand is identical on every install — forwarding
    it would shadow the connector's linked-owner fallback (which actually
    disambiguates) with a uniform label. Only customized names are forwarded."""
    monkeypatch.delenv("GATEWAY_RELAY_DISPLAY_NAME", raising=False)

    class _Skin:
        def get_branding(self, key, fallback=""):
            return "Hermes Agent" if key == "agent_name" else fallback

    monkeypatch.setattr("hermes_cli.skin_engine.get_active_skin", lambda: _Skin())
    assert relay.relay_display_name() is None


# ───────────────── boot refresh routing on a multiplexed gateway ─────────────────


def _boot_with_expired_login(tmp_path, monkeypatch, *, env_file: str, stored_portal: str) -> list[str]:
    """Launch home whose Nous access token expired while the box slept, so the startup
    self-provision is the first caller to refresh it. Returns the Portal URLs the refresh used."""
    launch_home = tmp_path / ".hermes"
    launch_home.mkdir()
    (launch_home / ".env").write_text(env_file, encoding="utf-8")
    (launch_home / "auth.json").write_text(json.dumps({
        "active_provider": "provider-a",
        "providers": {"provider-a": {
            "portal_base_url": stored_portal,
            "access_token": "expired-access-token", "refresh_token": "refresh-token",
            "expires_at": "2000-01-01T00:00:00+00:00",
        }},
    }), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch_home))
    for name in ("HERMES_PORTAL_BASE_URL", "PROVIDER_A_PORTAL_URL", "PROVIDER_A_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay, "relay_url", lambda: "wss://connector.example/relay")
    monkeypatch.setattr(relay, "register_relay_adapter", lambda: False)
    portals: list[str] = []

    def _refresh(**kwargs):
        portals.append(kwargs["portal_base_url"])
        raise RuntimeError("stop before any network call")

    monkeypatch.setattr("hermes_cli.auth._refresh_nous_or_quarantine", _refresh)
    return portals


def test_startup_idp_secret_ref_keeps_launch_env_value_when_multiplexed(tmp_path, monkeypatch):
    """Only the Nous token step runs in the launch profile's scope: a ``${VAR}`` IdP secret injected
    into the launch env (systemd, ``op run``) still reaches the IdP, as it did unscoped."""
    import io
    from unittest.mock import Mock

    launch_home = tmp_path / ".hermes"
    launch_home.mkdir()
    (launch_home / ".env").write_text("", encoding="utf-8")
    (launch_home / "config.yaml").write_text(
        "gateway:\n  idp:\n    token_url: https://idp.example/token\n"
        "    client_id: relay-client\n    client_secret: ${RELAY_IDP_SECRET}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(launch_home))
    # The autouse fixture stubs config reads; this test needs the real ``${VAR}`` expansion.
    from hermes_cli.config_effective import load_user_config_effective
    monkeypatch.setattr("gateway.run._load_gateway_config",
                        lambda config_path=None: load_user_config_effective(launch_home / "config.yaml"))
    monkeypatch.setenv("RELAY_IDP_SECRET", "injected-launch-secret")
    for name in ("GATEWAY_RELAY_IDP_TOKEN_URL", "GATEWAY_RELAY_IDP_CLIENT_ID",
                 "GATEWAY_RELAY_IDP_CLIENT_SECRET", "GATEWAY_RELAY_IDP_SCOPE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(relay, "relay_url", lambda: "wss://connector.example/relay")
    monkeypatch.setattr(relay, "register_relay_adapter", lambda: False)
    monkeypatch.setattr(relay, "_post_provision", Mock(return_value={}))
    bodies: list[str] = []

    def _idp(req, timeout=None):
        bodies.append(req.data.decode())
        return io.BytesIO(b'{"access_token": "idp-workload-token"}')

    monkeypatch.setattr("urllib.request.urlopen", _idp)
    secret_scope.set_multiplex_active(True)

    GatewayStartupMixin._start_register_plugins_relay_hooks()

    assert len(bodies) == 1
    assert "client_secret=injected-launch-secret" in bodies[0]

