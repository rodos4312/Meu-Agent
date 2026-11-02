"""Retired payment commands and RPCs are absent; ordinary agent usage remains local."""

import socket

import pytest

from hermes_cli.commands import resolve_command
from tui_gateway import contracts, server


@pytest.mark.parametrize("method", [
    "billing.state", "billing.charge", "billing.charge_status", "billing.auto_reload",
    "billing.keep_going_on_credits", "billing.step_up", "subscription.state",
    "subscription.preview", "subscription.change", "subscription.resume", "subscription.upgrade",
    "usage.bars",
])
def test_removed_payment_rpc_is_unknown_without_any_network_work(method, monkeypatch):
    attempts = []

    def connect(_socket, address):
        attempts.append(address)
        raise AssertionError(f"Unexpected payment connection: {address}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    reply = server.handle_request({"jsonrpc": "2.0", "id": "removed", "method": method, "params": {}})
    assert reply["error"]["code"] == -32601
    assert method not in contracts.METHODS
    assert attempts == []


def test_payment_commands_are_removed_but_usage_and_skills_remain():
    for name in ("topup", "subscription", "upgrade"):
        assert resolve_command(name) is None
    for name in ("usage", "skills", "model"):
        assert resolve_command(name) is not None


def test_session_usage_keeps_local_tokens_and_cost_without_network(monkeypatch):
    usage = {"calls": 2, "input": 120, "output": 30, "total": 150, "cost_usd": 0.025}
    session = {"agent": None, "_metadata_mirror": {"usage": usage}}
    monkeypatch.setitem(server._sessions, "local-usage", session)

    def connect(_socket, address):
        raise AssertionError(f"Local usage must not connect to {address}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    result = server.handle_request({
        "jsonrpc": "2.0", "id": "usage", "method": "session.usage",
        "params": {"session_id": "local-usage"},
    })
    assert result["result"] == usage
