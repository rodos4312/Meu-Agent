"""The retired Nous free-tier RPCs cannot mint credentials, nudge users or run challenges."""

import importlib.util
import socket

import pytest

from hermes_constants import get_hermes_home
from tui_gateway import contracts, server


@pytest.mark.parametrize("method", [
    "free_tier.status", "free_tier.provision", "free_tier.ack_notice",
    "free_tier.claim_nudge", "free_tier.challenge_result",
])
def test_retired_free_tier_rpc_is_unknown_without_network_or_state_changes(method, monkeypatch):
    home = get_hermes_home()  # tests/conftest.py owns this isolated directory
    state = home / "auth.json"
    original = '{"providers":{"nous":{"auth_method":"oauth","access_token":"old-test-token"}}}'
    state.write_text(original, encoding="utf-8")
    existing = sorted(p.name for p in home.iterdir())
    attempts = []

    def connect(_socket, address):
        attempts.append(address)
        raise AssertionError(f"Retired Nous RPC attempted a connection: {address}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    reply = server.handle_request({"jsonrpc": "2.0", "id": "retired", "method": method, "params": {}})
    assert reply["error"]["code"] == -32601
    assert method not in contracts.METHODS
    assert attempts == []
    assert state.read_text(encoding="utf-8") == original
    assert sorted(p.name for p in home.iterdir()) == existing


@pytest.mark.parametrize("module", [
    "tui_gateway.methods_free_tier", "tui_gateway.free_tier_task_done", "hermes_cli.free_tier_offer",
])
def test_retired_rpc_and_offer_implementations_are_removed(module):
    assert importlib.util.find_spec(module) is None
